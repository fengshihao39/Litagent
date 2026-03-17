"""
Litagent - 本地 PDF 深度解析服务

接收上传的 PDF 文件，执行完整深度解析流程：
  1. PyMuPDF 解析全文 + 中/英文章节提取
  2. Chunk 切分 + DeepSeek 语义检索
  3. 基础信息抽取（标题/作者/年份/摘要/关键词/页数）
  4. 全文结构化解读（8 个维度）
  5. 答辩辅助输出（4 种模式）
  6. 章节内容返回（6 个章节）

暴露给 API 层的主入口：
  analyze_pdf_file(pdf_bytes, filename) -> dict
  ask_question(paper_key, question, context_text) -> str

返回结构（analyze_pdf_file）：
{
  "paper_key":      str,
  "filename":       str,
  "basic_info":     dict,      # 标题/作者/年份/摘要/关键词/页数
  "structured":     dict,      # 8维结构化解读（含证据片段编号）
  "defense":        dict,      # 答辩辅助（4种格式）
  "sections":       dict,      # 6个章节原文内容
  "chunks":         list[dict],# 所有 chunk（供前端证据联动）
  "retrieved":      list[dict],# 语义检索 top-k 证据片段
  "page_count":     int,
  "char_count":     int,
  "is_chinese":     bool,
  "source":         str,
}
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
from pathlib import Path

from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key
from litagent.backend.app.services.chunk_service import (
    build_chunks,
    format_chunks_for_prompt,
)
from litagent.backend.app.services.pdf_parser import parse_pdf
from litagent.backend.app.services.retrieval_service import (
    get_or_build_chunks,
    retrieve_top_chunks,
)

logger = logging.getLogger(__name__)

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)

# 缓存目录（与 pdf_parser.py / retrieval_service.py 保持一致，用 parents[5]）
_PARSED_CACHE_DIR = Path(__file__).parents[5] / "data" / "parsed"
_PARSED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_ANALYZE_CACHE_DIR = Path(__file__).parents[5] / "data" / "analyze"
_ANALYZE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Prompts ──────────────────────────────────────────────────────────────────

_BASIC_INFO_PROMPT = """\
你是一名学术论文解析专家。请从以下论文文本中提取基础信息。

你必须以 JSON 格式返回，字段如下：
{
  "title": "论文标题（字符串）",
  "authors": ["作者1", "作者2"],
  "year": "发表年份（字符串，如 2024）",
  "abstract": "摘要内容（字符串，完整摘要，中文论文返回中文摘要）",
  "keywords": ["关键词1", "关键词2"],
  "venue": "期刊或会议名称（找不到写空字符串）"
}

规则：
- 如果找不到某字段，返回空字符串或空数组
- abstract 优先返回中文摘要（若论文有中文摘要）
- 只返回 JSON，不加任何解释
"""

_STRUCTURED_ANALYSIS_PROMPT = """\
你是一名专业科研助手，擅长基于证据做深度论文解读。
以下是从论文全文中通过语义检索得到的最相关片段（每段标注了编号和所属章节）。
请严格基于这些证据片段输出结构化分析报告，每项 3~6 句话，在括号内标注依据来自哪个片段编号。

输出格式必须严格如下（保留方括号格式）：

【研究背景】
（该研究针对什么领域背景和现实问题，依据：片段X）

【问题定义】
（作者试图解决的核心科学问题或技术挑战，依据：片段X）

【核心方法】
（提出了什么方法/模型/框架，关键设计思路，依据：片段X）

【关键公式与模型思想】
（核心数学形式或模型思想，用自然语言描述，依据：片段X）

【实验设置】
（使用了什么数据集/仿真场景、基线方法、评估指标，依据：片段X）

【结果与结论】
（实验结果表明什么，取得了哪些性能提升或发现，依据：片段X）

【创新点】
（与已有工作相比，核心创新和贡献是什么，依据：片段X）

【局限性】
（作者承认的局限，或尚未解决的问题，依据：片段X）

规则：
- 每条结论必须有明确的片段编号作为依据
- 片段中确实找不到的信息，写"证据片段中未涉及"
- 不得根据模型自身知识补充片段未提及的内容
- 只输出上述结构内容，不加任何前缀或后缀说明
"""

_DEFENSE_PROMPT = """\
你是一名科研答辩辅助专家。请基于以下论文信息，生成4种答辩辅助材料。

必须以 JSON 格式返回：
{
  "one_sentence": "一句话总结（25字以内，突出核心贡献）",
  "detailed": "详细汇报版（200字，包含背景、方法、结论、创新点）",
  "ppt_points": ["PPT要点1", "PPT要点2", "PPT要点3", "PPT要点4", "PPT要点5"],
  "likely_questions": [
    "可能被追问的问题1",
    "可能被追问的问题2",
    "可能被追问的问题3",
    "可能被追问的问题4",
    "可能被追问的问题5"
  ]
}

规则：
- 基于提供的论文内容，不编造信息
- ppt_points 精炼，每条不超过 30 字
- likely_questions 针对方法细节、实验设计、创新点的真实追问
- 只返回 JSON，不加任何解释
"""

_QA_SYSTEM_PROMPT = """\
你是一名专业科研助手，正在帮助用户深入理解一篇学术论文。
请基于以下论文相关内容回答用户的问题。

回答要求：
- 基于提供的论文内容，不编造不在内容中的信息
- 语言清晰，可以适当用专业术语但要解释
- 如果论文内容中确实没有答案，明确说明"论文中未找到相关内容"
- 回答长度适中（100~300字）
"""

# ── 检索任务描述 ───────────────────────────────────────────────────────────────

_RETRIEVAL_TASK = (
    "提取该论文的核心研究问题、提出的方法或模型、实验设置与数据集、"
    "主要实验结论、创新贡献、研究局限性，以及研究背景和应用场景"
)


# ── 缓存工具 ───────────────────────────────────────────────────────────────────


def _make_paper_key_from_bytes(pdf_bytes: bytes) -> str:
    """根据 PDF 内容的 MD5 生成唯一标识。"""
    return "upload_" + hashlib.md5(pdf_bytes).hexdigest()[:20]


def _load_analyze_cache(paper_key: str) -> dict | None:
    p = _ANALYZE_CACHE_DIR / f"{paper_key}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_analyze_cache(paper_key: str, data: dict) -> None:
    try:
        p = _ANALYZE_CACHE_DIR / f"{paper_key}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("解析结果缓存写入失败: %s", e)


# ── 基础信息抽取 ───────────────────────────────────────────────────────────────


def _extract_basic_info(full_text: str, page_count: int) -> dict:
    """从全文前段抽取基础信息（标题/作者/年份/摘要/关键词）。"""
    # 取前 3000 字（通常封面+摘要在最前面）
    sample = full_text[:3000]
    user_content = f"【论文文本（前段）】\n\n{sample}"

    raw = "{}"
    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _BASIC_INFO_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=2000,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        info = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("基础信息 JSON 解析失败，尝试修复: %s", e)
        # 截断不完整的 JSON 时，尝试提取已有字段
        try:
            # 找到最后一个完整的字段结束位置
            raw_fixed = raw[: raw.rfind(",")].rstrip() + "\n}"
            info = json.loads(raw_fixed)
        except Exception:
            info = {}
    except Exception as e:
        logger.error("基础信息抽取失败: %s", e)
        info = {}

    # 补充页数
    info["page_count"] = page_count
    # 保证字段完整
    info.setdefault("title", "")
    info.setdefault("authors", [])
    info.setdefault("year", "")
    info.setdefault("abstract", "")
    info.setdefault("keywords", [])
    info.setdefault("venue", "")

    return info


# ── 结构化解读 ─────────────────────────────────────────────────────────────────


def _generate_structured_analysis(
    retrieved_chunks: list[dict],
    basic_info: dict,
) -> str:
    """基于检索片段生成 8 维结构化解读。"""
    meta_parts = []
    if basic_info.get("title"):
        meta_parts.append(f"标题：{basic_info['title']}")
    if basic_info.get("venue"):
        meta_parts.append(f"期刊/会议：{basic_info['venue']}")
    if basic_info.get("year"):
        meta_parts.append(f"年份：{basic_info['year']}")
    if basic_info.get("keywords"):
        kws = basic_info["keywords"]
        if isinstance(kws, list):
            meta_parts.append(f"关键词：{', '.join(kws[:8])}")

    meta_text = "\n".join(meta_parts)
    evidence_text = format_chunks_for_prompt(retrieved_chunks)

    user_content = ""
    if meta_text:
        user_content += f"【论文基本信息】\n{meta_text}\n\n"
    user_content += f"【检索到的证据片段】\n\n{evidence_text}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _STRUCTURED_ANALYSIS_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=2500,
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        n_chunks = len(retrieved_chunks)
        return (
            f"> 本解读基于 RAG 检索生成（从全文提炼 {n_chunks} 个证据片段）\n\n"
            f"{content}"
        )
    except Exception as e:
        logger.error("结构化解读生成失败: %s", e)
        return "AI 解读生成失败，请稍后重试。"


# ── 答辩辅助输出 ───────────────────────────────────────────────────────────────


def _generate_defense_output(
    structured_text: str,
    basic_info: dict,
) -> dict:
    """生成4种答辩辅助材料。"""
    title = basic_info.get("title") or ""
    abstract = basic_info.get("abstract") or ""

    user_content = f"【论文标题】\n{title}\n\n【摘要】\n{abstract}\n\n【深度解读摘要】\n{structured_text[:2000]}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _DEFENSE_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=1200,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "{}").strip()
        result = json.loads(raw)
    except Exception as e:
        logger.error("答辩辅助生成失败: %s", e)
        result = {}

    result.setdefault("one_sentence", "")
    result.setdefault("detailed", "")
    result.setdefault("ppt_points", [])
    result.setdefault("likely_questions", [])
    return result


# ── 问答接口 ───────────────────────────────────────────────────────────────────


def ask_question_on_paper(
    question: str,
    paper_key: str,
    top_k: int = 5,
) -> dict:
    """
    针对已解析论文的问答接口。

    Args:
        question:  用户问题
        paper_key: 论文唯一标识（用于检索缓存的 chunks）
        top_k:     检索证据片段数量

    Returns:
        {
          "answer":   str,
          "evidence": list[dict],  # 检索到的支撑片段
        }
    """
    # 从缓存加载 chunks
    chunks = get_or_build_chunks(None, paper_key)  # type: ignore[arg-type]
    if not chunks:
        return {"answer": "论文 chunks 不存在，请重新上传解析。", "evidence": []}

    # 语义检索
    retrieved = retrieve_top_chunks(chunks, question, top_k=top_k)

    # 生成回答
    evidence_text = format_chunks_for_prompt(retrieved)
    user_content = f"【论文相关内容】\n\n{evidence_text}\n\n【用户问题】\n{question}"

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _QA_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            max_tokens=600,
            temperature=0.3,
        )
        answer = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("问答生成失败: %s", e)
        answer = "AI 回答生成失败，请稍后重试。"

    return {"answer": answer, "evidence": retrieved}


# ── 主入口 ────────────────────────────────────────────────────────────────────


def analyze_pdf_file(
    pdf_bytes: bytes, filename: str, force_reanalyze: bool = False
) -> dict:
    """
    本地 PDF 深度解析主入口。

    Args:
        pdf_bytes:       PDF 文件的二进制内容
        filename:        原始文件名（用于展示）
        force_reanalyze: 是否强制重新解析（忽略缓存）

    Returns:
        完整解析结果字典
    """
    paper_key = _make_paper_key_from_bytes(pdf_bytes)
    logger.info("开始深度解析: %s (key=%s)", filename, paper_key)

    # ── 命中完整解析缓存 ──
    if not force_reanalyze:
        cached = _load_analyze_cache(paper_key)
        if cached:
            logger.info("命中深度解析缓存: %s", paper_key)
            return cached

    # ── Step 1: 写入临时文件，解析 PDF ──
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)

    try:
        parsed = parse_pdf(tmp_path, paper_key)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass

    if parsed.get("source", "").startswith("error"):
        return {
            "paper_key": paper_key,
            "filename": filename,
            "error": parsed["source"],
            "page_count": 0,
        }

    full_text = parsed.get("full_text") or ""
    sections = parsed.get("sections") or {}
    page_count = parsed.get("page_count", 0)
    char_count = parsed.get("char_count", 0)
    is_chinese = parsed.get("is_chinese", False)

    # ── Step 2: 切 chunk + 语义检索 ──
    chunks = get_or_build_chunks(parsed, paper_key)
    total_chunks = len(chunks)
    logger.info("chunk 数量: %d", total_chunks)

    retrieved = retrieve_top_chunks(chunks, _RETRIEVAL_TASK, top_k=8)
    logger.info("检索到 %d 个证据片段", len(retrieved))

    # ── Step 3: 基础信息抽取 ──
    # 直接用原始全文（不是 sections 拼接版），前3000字包含封面+摘要
    import fitz  # type: ignore[import]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp2:
        # 重新写临时文件用于提取原始前段文本
        tmp2.write(pdf_bytes)
        tmp2_path = Path(tmp2.name)
    try:
        doc = fitz.open(str(tmp2_path))
        raw_pages = [doc[i].get_text() for i in range(min(8, len(doc)))]
        doc.close()
        raw_front = "\n".join(raw_pages)
    except Exception:
        raw_front = full_text
    finally:
        try:
            tmp2_path.unlink()
        except Exception:
            pass

    basic_info = _extract_basic_info(raw_front, page_count)
    # 如果从原始前段没提取到摘要，用 sections['abstract'] 补充
    if not basic_info.get("abstract") and sections.get("abstract"):
        basic_info["abstract"] = sections["abstract"][:1000]
    # 如果标题为空，从文件名兜底（去掉扩展名，下划线前最后一段通常是作者名）
    if not basic_info.get("title"):
        stem = Path(filename).stem  # e.g. "脉冲噪声下的水声阵列DOA估计方法研究_戴泽华"
        parts = stem.rsplit("_", 1)
        basic_info["title"] = parts[0] if len(parts) > 1 else stem
        if len(parts) > 1 and not basic_info.get("authors"):
            basic_info["authors"] = [parts[1]]
    logger.info("基础信息抽取完成: title=%s", basic_info.get("title", "")[:30])

    # ── Step 4: 结构化解读 ──
    structured_text = _generate_structured_analysis(retrieved, basic_info)
    logger.info("结构化解读生成完成")

    # ── Step 5: 答辩辅助输出 ──
    defense = _generate_defense_output(structured_text, basic_info)
    logger.info("答辩辅助生成完成")

    # ── 组装结果 ──
    result = {
        "paper_key": paper_key,
        "filename": filename,
        "basic_info": basic_info,
        "structured": structured_text,
        "defense": defense,
        "sections": sections,
        "chunks": chunks,
        "retrieved": retrieved,
        "page_count": page_count,
        "char_count": char_count,
        "total_chunks": total_chunks,
        "is_chinese": is_chinese,
        "source": parsed.get("source", "pdf"),
    }

    # 缓存结果（chunks 数据较大，单独存储不影响主缓存读取速度）
    _save_analyze_cache(paper_key, result)
    logger.info("深度解析完成并缓存: %s", paper_key)

    return result
