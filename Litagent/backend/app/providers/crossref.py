"""
Litagent - FastAPI 后端 Crossref 搜索接口
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from Litagent.backend.app.providers.base import ProviderBase

CROSSREF_API_BASE = "https://api.crossref.org/works"


class CrossrefProvider(ProviderBase):
    """Crossref provider 封装。"""

    name = "crossref"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        min_year: Optional[int] = None,
        sort_by: str = "relevance",
    ) -> List[Dict]:
        return search_papers(
            query,
            max_results=max_results,
            min_year=min_year,
            sort_by=sort_by,
        )


def search_papers(
    query: str,
    max_results: int = 8,
    min_year: Optional[int] = None,
    sort_by: str = "relevance",
) -> List[Dict]:
    """在 Crossref 上搜索文献。

    Args:
        query (str): 搜索关键词。
        max_results (int, optional): 搜索返回的最大数量. Defaults to 8.
        min_year (Optional[int], optional): 返回文献的最早年份. Defaults to None.
        sort_by (str, optional): 文献的排序方法. Defaults to "relevance".

    Returns:
        List[Dict]: 返回搜索到的文献或报错信息。
    """

    polite_email = "25209100302@stu.xidian.edu.cn"
    user_agent = f"StarfireAgent/1.0 (mailto:{polite_email})"

    params = {
        "query": query,
        "rows": min(max_results * 2, 50),
        "select": (
            "DOI,title,author,published,container-title,abstract,is-referenced-by-count,",
            "subject,URL",
        ),
        "sort": sort_by,
        "order": "desc",
    }

    if min_year:
        params["filter"] = f"from-pub-date:{min_year}"

    url = f"{CROSSREF_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return [{"error": f"Crossref API 错误 {e.code}: {e}", "source": "crossref"}]
    except (urllib.error.URLError, TimeoutError) as e:
        return [{"error": f"Crossref 网络请求失败: {e}", "source": "crossref"}]

    return _parse_crossref_response(content, max_results)


def _format_published_date(date_parts: List[int]) -> str:
    if len(date_parts) >= 3:
        return f"{date_parts[0]}-{date_parts[1]:02d}-{date_parts[2]:02d}"
    if len(date_parts) == 2:
        return f"{date_parts[0]}-{date_parts[1]:02d}-01"
    if len(date_parts) == 1:
        return f"{date_parts[0]}-01-01"
    return "unknown"


def _extract_authors(item: Dict) -> List[str]:
    authors = []
    for author in item.get("author", []):
        given = author.get("given", "")
        family = author.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            authors.append(name)
    return authors


def _extract_date_parts(item: Dict) -> List[int]:
    pub = item.get("published", {}) or item.get("published-print", {}) or {}
    return pub.get("date-parts", [[]])[0]


def _extract_venue(item: Dict) -> str:
    container = item.get("container-title", [])
    return container[0] if container else ""


def _extract_abs_url(item: Dict, doi: str) -> str:
    return item.get("URL", f"https://doi.org/{doi}" if doi else "")


def _parse_crossref_item(item: Dict) -> Optional[Dict]:
    title_list = item.get("title", [])
    title = title_list[0] if title_list else ""
    if not title.strip():
        return None

    date_parts = _extract_date_parts(item)
    doi = item.get("DOI", "")

    return {
        "source": "crossref",
        "arxiv_id": "",
        "doi": doi,
        "title": title,
        "authors": _extract_authors(item),
        "published": _format_published_date(date_parts),
        "year": str(date_parts[0]) if date_parts else "",
        "venue": _extract_venue(item),
        "categories": item.get("subject", []) or [],
        "summary": _clean_abstract(item.get("abstract", "")),
        "tldr": "",
        "citation_count": item.get("is-referenced-by-count", 0) or 0,
        "pdf_url": "",
        "abs_url": _extract_abs_url(item, doi),
    }


def _parse_crossref_response(json_content: str, max_results: int) -> List[Dict]:
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"响应解析失败: {e}", "source": "crossref"}]

    items = data.get("message", {}).get("items", [])
    if not items:
        return []

    papers: List[Dict] = []
    for item in items:
        parsed = _parse_crossref_item(item)
        if parsed:
            papers.append(parsed)

    return papers[:max_results]


def _clean_abstract(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return " ".join(clean.split()).strip()
