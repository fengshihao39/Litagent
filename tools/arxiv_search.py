"""
arXiv 论文搜索工具
支持按关键词、领域分类搜索，默认聚焦电子信息/AI/雷达方向
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import time
from typing import List, Dict, Optional

# 西电三大方向对应的 arXiv 分类
XIDIAN_CATEGORIES = {
    "人工智能": ["cs.AI", "cs.LG", "cs.CV", "cs.CL"],
    "电子信息": ["eess.SP", "eess.IV", "eess.AS", "cs.IT"],
    "雷达信号处理": ["eess.SP", "cs.IT", "eess.SY"],
}

# 所有默认分类（去重）
DEFAULT_CATEGORIES = list({cat for cats in XIDIAN_CATEGORIES.values() for cat in cats})

ARXIV_API_BASE = "https://export.arxiv.org/api/query"


def search_papers(
    query: str,
    max_results: int = 8,
    categories: Optional[List[str]] = None,
    sort_by: str = "relevance",
) -> List[Dict]:
    """
    搜索 arXiv 论文

    参数:
        query        : 搜索关键词（英文效果最好）
        max_results  : 返回论文数量，默认 8 篇
        categories   : arXiv 分类列表，None 则使用西电默认三大方向
        sort_by      : 排序方式 relevance | lastUpdatedDate | submittedDate

    返回:
        List[Dict]，每个 Dict 包含论文的结构化信息
    """
    if categories is None:
        categories = DEFAULT_CATEGORIES

    cat_filter = " OR ".join([f"cat:{c}" for c in categories])
    search_query = f"({query}) AND ({cat_filter})"

    params = {
        "search_query": search_query,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }

    url = f"{ARXIV_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            content = response.read().decode("utf-8")
    except Exception as e:
        return [{"error": f"网络请求失败: {e}"}]

    return _parse_arxiv_response(content)


def _parse_arxiv_response(xml_content: str) -> List[Dict]:
    """解析 arXiv API 返回的 XML"""
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    root = ET.fromstring(xml_content)
    papers = []

    for entry in root.findall("atom:entry", ns):

        def _text(tag: str) -> str:
            el = entry.find(tag, ns)
            return (el.text or "").strip() if el is not None else ""

        raw_id = _text("atom:id")
        arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]
        title = " ".join(_text("atom:title").split())
        summary = " ".join(_text("atom:summary").split())

        authors = []
        for a in entry.findall("atom:author", ns):
            name_el = a.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        published = _text("atom:published")[:10]
        updated = _text("atom:updated")[:10]
        categories = [tag.get("term", "") for tag in entry.findall("atom:category", ns)]

        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "published": published,
                "updated": updated,
                "categories": categories,
                "summary": summary,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            }
        )

        time.sleep(0.1)

    return papers


def format_paper_brief(paper: Dict, index: Optional[int] = None) -> str:
    """将论文信息格式化为简洁的可读字符串"""
    if "error" in paper:
        return f"[错误] {paper['error']}"

    prefix = f"[{index}] " if index is not None else ""
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " 等"

    return (
        f"{prefix}**{paper['title']}**\n"
        f"   作者: {authors_str}\n"
        f"   时间: {paper['published']}  |  ID: {paper['arxiv_id']}\n"
        f"   分类: {', '.join(paper['categories'][:3])}\n"
        f"   链接: {paper['abs_url']}\n"
        f"   摘要: {paper['summary'][:200]}...\n"
    )


def format_papers_list(papers: List[Dict]) -> str:
    """格式化整个搜索结果列表"""
    if not papers:
        return "未找到相关论文，请尝试更换关键词。"
    if "error" in papers[0]:
        return f"搜索失败: {papers[0]['error']}"

    lines = [f"共找到 {len(papers)} 篇相关论文：\n"]
    for i, paper in enumerate(papers, 1):
        lines.append(format_paper_brief(paper, index=i))
        lines.append("")

    return "\n".join(lines)
