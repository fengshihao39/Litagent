"""
Litagent - RAG 全流程服务

完整流程：
  1. 解析 PDF → build_chunks → 缓存
  2. DeepSeek 语义打分 → 检索 top-k 证据片段
  3. 用检索到的证据片段 + 论文元数据生成结构化总结
  4. 降级策略：PDF 不可用时 → 摘要兜底

本模块是第三阶段的核心入口，暴露 run_rag_summary() 给 API 层调用。

返回结构：
  {
    "summary":        str,          # 结构化总结文本
    "source":         str,          # "rag" | "pdf_direct" | "abstract_fallback" | "error: ..."
    "retrieved_chunks": list[dict], # 检索到的证据片段（含相关度分数）
    "total_chunks":   int,          # 总 chunk 数
    "page_count":     int,
    "pdf_available":  bool,
  }
"""

from __future__ import annotations

import logging

from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key
from litagent.backend.app.services.chunk_service import format_chunks_for_prompt
from litagent.backend.app.services.paper_detail_service import _make_paper_key
from litagent.backend.app.services.pdf_downloader import download_pdf, resolve_pdf_url
from litagent.backend.app.services.pdf_parser import (
    make_fallback_from_abstract,
    parse_pdf,
)
from litagent.backend.app.services.retrieval_service import (
    get_or_build_chunks,
    retrieve_top_chunks,
)

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)

# ── RAG 总结 Prompt ───────────────────────────────────────────────────────────

_RAG_SUMMARY_PROMPT = """\
你是一名专业科研助手，擅长基于证据做深度论文解读。
以下是从论文全文中通过语义检索得到的最相关片段（每段标注了编号和所属章节）。
请严格基于这些证据片段输出结构化分析报告，不得使用片段之外的信息。

输出格式必须严格如下，每项 3~6 句话，有据可依，并在括号内标注依据来自哪个片段编号：

【研究背景】
（该研究针对什么领域背景和现实问题，依据：片段X）

【研究问题】
（作者试图解决的核心科学问题或技术挑战，依据：片段X）

【核心方法】
（提出了什么方法/模型/框架，关键设计是什么，依据：片段X）

【实验设置】
（使用了什么数据集、基线方法、评估指标，依据：片段X）

【主要结论】
（实验结果表明什么，取得了哪些性能提升或发现，依据：片段X）

【创新点】
（与已有工作相比，核心创新和贡献是什么，依据：片段X）

【应用场景】
（这项研究可以应用在哪些实际场景，依据：片段X）

【局限性与未来工作】
（作者承认的局限，或尚未解决的问题，依据：片段X）

规则：
- 每条结论必须有明确的片段编号作为依据
- 片段中确实找不到的信息，写"证据片段中未涉及"
- 不得根据模型自身知识补充片段未提及的内容
- 只输出上述结构内容，不加任何前缀或后缀说明
"""

# ── 检索任务描述（用于 retrieval_service 打分） ──────────────────────────────

_RETRIEVAL_TASK = (
    "提取该论文的核心研究问题、提出的方法或模型、实验设置与数据集、"
    "主要实验结论、创新贡献、研究局限性，以及研究背景和应用场景"
)

# ── 主入口 ────────────────────────────────────────────────────────────────────


def run_rag_summary(paper: dict, top_k: int = 8) -> dict:
    """
    RAG 全流程：PDF 解析 → chunk → 语义检索 → 生成结构化总结。

    Args:
        paper:  完整论文字典（含 pdf_url / arxiv_id / title / abstract 等）
        top_k:  检索返回的 top 证据片段数量

    Returns:
        {
          "summary":          str,
          "source":           str,
          "retrieved_chunks": list[dict],
          "total_chunks":     int,
          "page_count":       int,
          "pdf_available":    bool,
        }
    """
    title = paper.get("title") or ""
    abstract = paper.get("summary") or paper.get("abstract") or ""
    tldr = paper.get("tldr") or ""
    venue = paper.get("venue") or ""
    year = str(paper.get("year") or "")
    keywords = paper.get("keywords") or paper.get("categories") or []

    paper_key = _make_paper_key(paper)

    # ── Step 1: 尝试获取 PDF ──
    pdf_url = resolve_pdf_url(paper)
    pdf_path = None
    if pdf_url:
        pdf_path = download_pdf(pdf_url, paper_key)

    # ── Step 2: 解析 PDF ──
    if pdf_path:
        parsed = parse_pdf(pdf_path, paper_key)
    else:
        parsed = make_fallback_from_abstract(abstract, tldr)

    pdf_available = pdf_path is not None
    page_count = parsed.get("page_count", 0)
    parse_source = parsed.get("source", "abstract_fallback")

    # 如果解析来源是 error，降级走摘要兜底总结
    if parse_source.startswith("error"):
        logger.warning("PDF 解析失败，降级到摘要兜底: %s", parse_source)
        summary = _abstract_fallback_summary(abstract, title, venue, year, keywords)
        return {
            "summary": summary,
            "source": "abstract_fallback",
            "retrieved_chunks": [],
            "total_chunks": 0,
            "page_count": 0,
            "pdf_available": False,
        }

    # ── Step 3: 切 chunk ──
    chunks = get_or_build_chunks(parsed, paper_key)
    total_chunks = len(chunks)

    if not chunks:
        logger.warning("chunk 列表为空，降级到摘要兜底")
        summary = _abstract_fallback_summary(abstract, title, venue, year, keywords)
        return {
            "summary": summary,
            "source": "abstract_fallback",
            "retrieved_chunks": [],
            "total_chunks": 0,
            "page_count": page_count,
            "pdf_available": pdf_available,
        }

    # ── Step 4: 语义检索 top-k ──
    logger.info("开始语义检索，共 %d 个 chunks，取 top %d", total_chunks, top_k)
    retrieved = retrieve_top_chunks(chunks, _RETRIEVAL_TASK, top_k=top_k)
    logger.info("检索完成，返回 %d 个证据片段", len(retrieved))

    # ── Step 5: 生成 RAG 总结 ──
    summary = _generate_rag_summary(
        retrieved_chunks=retrieved,
        title=title,
        venue=venue,
        year=year,
        keywords=keywords if isinstance(keywords, list) else [],
    )

    source = "rag" if pdf_available else "rag_abstract"

    return {
        "summary": summary,
        "source": source,
        "retrieved_chunks": retrieved,
        "total_chunks": total_chunks,
        "page_count": page_count,
        "pdf_available": pdf_available,
    }


# ── 生成函数 ───────────────────────────────────────────────────────────────────


def _build_meta(title: str, venue: str, year: str, keywords: list[str]) -> str:
    parts = []
    if title:
        parts.append(f"标题：{title}")
    if venue:
        parts.append(f"期刊/会议：{venue}")
    if year:
        parts.append(f"年份：{year}")
    if keywords:
        parts.append(f"关键词：{', '.join(keywords[:8])}")
    return "\n".join(parts)


def _generate_rag_summary(
    retrieved_chunks: list[dict],
    title: str,
    venue: str,
    year: str,
    keywords: list[str],
) -> str:
    """基于检索到的证据片段生成结构化总结。"""
    meta = _build_meta(title, venue, year, keywords)
    evidence_text = format_chunks_for_prompt(retrieved_chunks)

    user_content = ""
    if meta:
        user_content += f"【论文基本信息】\n{meta}\n\n"
    user_content += f"【检索到的证据片段】\n\n{evidence_text}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _RAG_SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        n_chunks = len(retrieved_chunks)
        return (
            f"> 本总结基于 RAG 检索生成（从全文 {n_chunks} 个证据片段中提炼）\n\n"
            f"{content}"
        )
    except Exception as e:
        logger.error("RAG 总结生成失败: %s", e)
        return "AI 总结生成失败，请稍后重试。"


# ── 摘要兜底（无 PDF 时） ──────────────────────────────────────────────────────

_ABSTRACT_FALLBACK_PROMPT = """\
你是一名科研助手，擅长解读学术论文。
用户仅提供了论文的摘要和部分元数据。
请基于这些内容输出结构化分析，每项 2~4 句话。

输出格式：

【研究背景】
【研究问题】
【核心方法】
【主要结论】
【应用场景】
【局限性】

规则：
- 只能基于摘要内容，推断部分在末尾注明"（AI 推断，非全文依据）"
- 找不到的信息写"摘要中未说明"
- 只输出上述结构，不加任何前缀或解释
"""


def _abstract_fallback_summary(
    abstract: str,
    title: str,
    venue: str,
    year: str,
    keywords: list[str],
) -> str:
    if not abstract.strip():
        return "暂无摘要，无法生成 AI 总结。"

    meta = _build_meta(title, venue, year, keywords)
    user_content = ""
    if meta:
        user_content += f"【论文基本信息】\n{meta}\n\n"
    user_content += f"【论文摘要】\n{abstract.strip()}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _ABSTRACT_FALLBACK_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        content = (resp.choices[0].message.content or "").strip()
        return f"> 本总结仅基于摘要生成（未能获取 PDF 全文）\n\n{content}"
    except Exception:
        return "AI 总结生成失败，请稍后重试。"
