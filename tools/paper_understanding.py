"""
论文理解模块
两阶段流程：
  Stage 1: 摘要相关性打分（0-10），>= 7 才触发全文解析
  Stage 2: 全文重点章节结构化总结（DeepSeek）
"""

import json
from typing import List, Dict, Optional

from openai import OpenAI

# ── DeepSeek 客户端 ───────────────────────────────────────

_client = OpenAI(
    api_key="x x x x",
    
    base_url="https://api.deepseek.com",
)

SCORE_THRESHOLD = 7  # 摘要评分阈值
MAX_DEEP_PAPERS = 5  # 每次最多深度解析篇数


# ── Stage 1: 摘要相关性评分 ──────────────────────────────


def score_abstract_relevance(abstract: str, query: str) -> int:
    """
    用 DeepSeek 对单篇论文摘要与查询的相关性打分 (0-10)
    失败时返回 5（中性分，不影响筛选）
    """
    if not abstract or not abstract.strip():
        return 3  # 无摘要，低分
    prompt = f"""你是一个学术文献评估专家。请评估以下论文摘要与研究查询的相关性。

研究查询：{query}

论文摘要：
{abstract[:800]}

请给出 0-10 的相关性评分（整数），其中：
- 0-3: 基本不相关
- 4-6: 部分相关
- 7-8: 较为相关
- 9-10: 高度相关，直接命中

只需返回一个整数，不要任何解释。"""

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0.0,
        )
        score_str = resp.choices[0].message.content.strip()
        score = int(score_str)
        return max(0, min(10, score))
    except Exception:
        return 5


def batch_score_abstracts(papers: List[Dict], query: str) -> List[Dict]:
    """
    对一批论文摘要评分，返回加了 relevance_score 字段的论文列表，
    并按分数降序排列
    """
    for paper in papers:
        # 兼容不同来源的摘要字段名：abstract（Crossref/IEEE）/ summary（arXiv/S2）
        abstract = paper.get("abstract") or paper.get("summary") or ""
        paper["relevance_score"] = score_abstract_relevance(abstract, query)

    papers.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
    return papers


def select_for_deep_analysis(papers: List[Dict]) -> List[Dict]:
    """
    从打过分的论文中，筛选出需要深度解析的论文（分数 >= 阈值，最多 MAX_DEEP_PAPERS 篇）
    """
    candidates = [p for p in papers if p.get("relevance_score", 0) >= SCORE_THRESHOLD]
    return candidates[:MAX_DEEP_PAPERS]


# ── Stage 2: 全文结构化总结 ──────────────────────────────


def summarize_paper_fulltext(paper: Dict, query: str) -> Dict:
    """
    对单篇论文进行深度结构化总结
    输入: paper dict（含 sections 字段，来自 pdf_loader）
    输出: 在 paper 上添加 deep_summary 字段

    deep_summary 结构:
    {
        "core_contribution": str,   # 核心贡献（1-2句）
        "method_overview": str,     # 方法概述
        "key_results": str,         # 主要实验结果
        "conclusion": str,          # 结论与局限
        "relevance_to_query": str,  # 与查询的具体关联
    }
    """
    sections = paper.get("sections") or paper.get("parsed_sections", {})
    full_text = paper.get("full_text", "")

    if not sections and not full_text:
        paper["deep_summary"] = _fallback_summary(paper, query)
        return paper

    # 构建分章节文本
    text_parts = []
    for title, content in sections.items():
        if content and content.strip():
            text_parts.append(f"[{title}]\n{content[:2000]}")

    if not text_parts and full_text:
        text_parts = [full_text[:6000]]

    combined_text = "\n\n".join(text_parts)[:6000]  # 总长度限制

    prompt = f"""你是一名资深学术研究员，请对以下论文进行结构化分析。

研究背景（用户查询）：{query}

论文标题：{paper.get("title", "未知")}

论文正文（关键章节）：
{combined_text}

请用 JSON 格式返回分析结果，包含以下字段（所有字段用中文回答）：
{{
  "core_contribution": "核心贡献，1-2句话",
  "method_overview": "方法/模型概述，3-5句话",
  "key_results": "主要实验结果与指标，2-4句话",
  "conclusion": "结论与局限性，1-2句话",
  "relevance_to_query": "与研究查询的具体关联，1-2句话"
}}

只返回 JSON，不要其他内容。"""

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )
        content = resp.choices[0].message.content.strip()
        # 去掉可能的 markdown 代码块
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        deep_summary = json.loads(content)
        paper["deep_summary"] = deep_summary
    except json.JSONDecodeError:
        # JSON 解析失败，降级为纯文本摘要
        paper["deep_summary"] = {"raw": content if "content" in dir() else "解析失败"}
    except Exception as e:
        paper["deep_summary"] = _fallback_summary(paper, query)

    return paper


def _fallback_summary(paper: Dict, query: str) -> Dict:
    """当全文不可用时，仅用摘要生成简略总结"""
    abstract = paper.get("abstract") or paper.get("summary") or ""
    if not abstract:
        return {"core_contribution": "无法获取论文内容", "relevance_to_query": "未知"}

    prompt = f"""基于以下摘要，简要总结这篇论文与"{query}"的关系（2-3句话，中文）：

{abstract[:600]}

只返回总结文本，不要其他内容。"""

    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        return {"core_contribution": text, "relevance_to_query": "基于摘要分析"}
    except Exception:
        return {"core_contribution": abstract[:300], "relevance_to_query": "基于摘要"}


# ── 批量深度分析（主入口）────────────────────────────────


def deep_analyze_papers(
    papers: List[Dict],
    query: str,
    pdf_loader_func=None,
) -> List[Dict]:
    """
    完整两阶段流程：
    1. 对所有论文摘要打分
    2. 筛选高分论文进行全文解析（如果提供了 pdf_loader_func）
    3. 对高分论文进行深度结构化总结

    参数：
        papers: 论文列表（来自 multi_search）
        query: 用户查询
        pdf_loader_func: 可选，接受 arxiv_id 返回解析结果的函数
                         如果为 None，则跳过全文解析，仅用摘要

    返回：所有论文（已打分），高分论文额外含 deep_summary 字段
    """
    print(f"  [理解] Stage 1: 对 {len(papers)} 篇论文评分...")
    papers = batch_score_abstracts(papers, query)

    candidates = select_for_deep_analysis(papers)
    print(
        f"  [理解] Stage 2: {len(candidates)} 篇论文进入深度分析"
        f"（评分>={SCORE_THRESHOLD}）"
    )

    for i, paper in enumerate(candidates):
        print(
            f"  [理解] 深度分析 {i + 1}/{len(candidates)}: {paper.get('title', '')[:50]}"
        )

        # 尝试获取全文
        if pdf_loader_func:
            arxiv_id = _extract_arxiv_id(paper)
            if arxiv_id:
                try:
                    parsed = pdf_loader_func(arxiv_id)
                    if not parsed.get("error"):
                        paper["sections"] = parsed["sections"]
                        paper["full_text"] = parsed["full_text"]
                        paper["pdf_parsed"] = True
                except Exception:
                    pass

        summarize_paper_fulltext(paper, query)

    return papers


def _extract_arxiv_id(paper: Dict) -> Optional[str]:
    """从论文 dict 中提取 arXiv ID"""
    # 直接有 arxiv_id 字段
    if paper.get("arxiv_id"):
        return paper["arxiv_id"]
    # 从 url 字段提取
    url = paper.get("url", "") or paper.get("pdf_url", "")
    if "arxiv.org" in url:
        import re

        m = re.search(r"(\d{4}\.\d{4,5})", url)
        if m:
            return m.group(1)
    # 从 doi 提取
    doi = paper.get("doi", "")
    if doi and "arxiv" in doi.lower():
        import re

        m = re.search(r"(\d{4}\.\d{4,5})", doi)
        if m:
            return m.group(1)
    return None


# ── 测试 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from xinghuo_agent.tools.pdf_loader import parse_arxiv_paper

    # 测试论文列表（模拟 multi_search 输出）
    test_papers = [
        {
            "title": "Attention Is All You Need",
            "abstract": (
                "The dominant sequence transduction models are based on complex recurrent "
                "or convolutional neural networks that include an encoder and a decoder. "
                "The best performing models also connect the encoder and decoder through "
                "an attention mechanism. We propose a new simple network architecture, "
                "the Transformer, based solely on attention mechanisms, dispensing with "
                "recurrence and convolutions entirely."
            ),
            "arxiv_id": "1706.03762",
            "year": 2017,
            "authors": ["Vaswani et al."],
        },
        {
            "title": "A Completely Unrelated Paper About Cooking",
            "abstract": "This paper discusses the art of making pasta and various Italian cuisines.",
            "arxiv_id": None,
            "year": 2020,
            "authors": ["Chef et al."],
        },
    ]

    query = "transformer self-attention mechanism neural machine translation"
    print(f"=== 测试 paper_understanding.py ===")
    print(f"查询：{query}\n")

    results = deep_analyze_papers(test_papers, query, pdf_loader_func=parse_arxiv_paper)

    for p in results:
        print(f"\n{'=' * 50}")
        print(f"标题：{p['title']}")
        print(f"相关性评分：{p.get('relevance_score', 'N/A')}")
        print(f"PDF解析：{'是' if p.get('pdf_parsed') else '否'}")
        if p.get("deep_summary"):
            ds = p["deep_summary"]
            for k, v in ds.items():
                print(f"  [{k}]: {str(v)[:200]}")
