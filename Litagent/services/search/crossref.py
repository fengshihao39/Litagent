"""
Crossref 论文搜索工具
特点：
  - 免费，无需 API Key
  - DOI 覆盖率极高，期刊/会议论文为主
  - 使用 Polite Pool：请求头带邮箱，限流更宽松
  - 与 arxiv_search / semantic_scholar_search 格式兼容
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import re
import time
from typing import List, Dict, Optional

CROSSREF_API = "https://api.crossref.org/works"

# Polite Pool：带上邮箱，Crossref 会优先处理
POLITE_EMAIL = "25209100302@stu.xidian.edu.cn"
USER_AGENT = f"StarfireAgent/1.0 (mailto:{POLITE_EMAIL})"


def search_papers(
    query: str,
    max_results: int = 8,
    min_year: Optional[int] = None,
    sort_by: str = "relevance",  # relevance | cited-by-count
) -> List[Dict]:
    """
    使用 Crossref API 搜索论文

    参数：
        query       : 搜索关键词（英文）
        max_results : 返回数量
        min_year    : 最早发表年份过滤
        sort_by     : 排序方式 relevance | cited-by-count

    返回：
        统一格式的论文列表（与其他搜索模块格式兼容）
    """
    params = {
        "query": query,
        "rows": min(max_results * 2, 50),  # 多取一些，方便过滤
        "select": "DOI,title,author,published,container-title,abstract,is-referenced-by-count,subject,URL",
        "sort": sort_by,
        "order": "desc",
    }

    if min_year:
        params["filter"] = f"from-pub-date:{min_year}"

    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return [{"error": f"Crossref API 错误 {e.code}: {e}", "source": "crossref"}]
    except Exception as e:
        return [{"error": f"Crossref 网络请求失败: {e}", "source": "crossref"}]

    return _parse_response(content, max_results)


def _parse_response(json_content: str, max_results: int) -> List[Dict]:
    """解析 Crossref API 返回的 JSON"""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"响应解析失败: {e}", "source": "crossref"}]

    items = data.get("message", {}).get("items", [])
    if not items:
        return []

    papers = []
    for item in items:
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""
        if not title.strip():
            continue

        # 作者
        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

        # 发表时间
        pub = item.get("published", {}) or item.get("published-print", {}) or {}
        date_parts = pub.get("date-parts", [[]])[0]
        if len(date_parts) >= 3:
            published = f"{date_parts[0]}-{date_parts[1]:02d}-{date_parts[2]:02d}"
        elif len(date_parts) == 2:
            published = f"{date_parts[0]}-{date_parts[1]:02d}-01"
        elif len(date_parts) == 1:
            published = f"{date_parts[0]}-01-01"
        else:
            published = "unknown"

        # 期刊/会议名
        container = item.get("container-title", [])
        venue = container[0] if container else ""

        # DOI 和链接
        doi = item.get("DOI", "")
        abs_url = item.get("URL", f"https://doi.org/{doi}" if doi else "")

        # 摘要（Crossref 部分论文有，部分没有）
        abstract = _clean_abstract(item.get("abstract", ""))

        # 引用数
        citation_count = item.get("is-referenced-by-count", 0) or 0

        # 研究领域（subject）
        categories = item.get("subject", []) or []

        papers.append(
            {
                "source": "crossref",
                "arxiv_id": "",
                "doi": doi,
                "title": title,
                "authors": authors,
                "published": published,
                "year": str(date_parts[0]) if date_parts else "",
                "venue": venue,
                "categories": categories,
                "summary": abstract,
                "tldr": "",
                "citation_count": citation_count,
                "pdf_url": "",
                "abs_url": abs_url,
            }
        )

    return papers[:max_results]


def _clean_abstract(text: str) -> str:
    """去除 Crossref 摘要里的 JATS XML 标签"""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return " ".join(clean.split()).strip()


def format_paper_brief(paper: Dict, index: Optional[int] = None) -> str:
    """格式化单篇论文为可读字符串"""
    if "error" in paper:
        return f"[错误] {paper['error']}"

    prefix = f"[{index}] " if index is not None else ""
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " 等"

    venue_str = f"  |  {paper['venue']}" if paper.get("venue") else ""
    citation_str = (
        f"  |  被引 {paper['citation_count']} 次" if paper.get("citation_count") else ""
    )
    doi_str = f"  |  DOI: {paper['doi']}" if paper.get("doi") else ""

    summary_preview = (
        paper["summary"][:200] + "..." if paper.get("summary") else "（无摘要）"
    )

    return (
        f"{prefix}**{paper['title']}**\n"
        f"   作者: {authors_str}\n"
        f"   时间: {paper['published']}{venue_str}{citation_str}\n"
        f"   来源: Crossref{doi_str}\n"
        f"   链接: {paper['abs_url']}\n"
        f"   摘要: {summary_preview}\n"
    )


# ── 测试 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    print("=== 测试 Crossref 搜索 ===\n")
    results = search_papers("radar target detection deep learning", max_results=4)

    if results and "error" in results[0]:
        print(f"错误: {results[0]['error']}")
    else:
        print(f"找到 {len(results)} 篇论文：\n")
        for i, p in enumerate(results, 1):
            print(format_paper_brief(p, index=i))
