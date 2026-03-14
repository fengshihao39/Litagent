"""
Crossref 论文搜索模块
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .base import ProviderBase


CROSSREF_API = "https://api.crossref.org/works"


class CrossrefProvider(ProviderBase):
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
    """使用 Crossref API 搜索论文"""
    polite_email = "25209100302@stu.xidian.edu.cn"
    user_agent = f"StarfireAgent/1.0 (mailto:{polite_email})"

    params = {
        "query": query,
        "rows": min(max_results * 2, 50),
        "select": "DOI,title,author,published,container-title,abstract,is-referenced-by-count,subject,URL",
        "sort": sort_by,
        "order": "desc",
    }

    if min_year:
        params["filter"] = f"from-pub-date:{min_year}"

    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return [{"error": f"Crossref API 错误 {e.code}: {e}", "source": "crossref"}]
    except Exception as e:
        return [{"error": f"Crossref 网络请求失败: {e}", "source": "crossref"}]

    return _parse_crossref_response(content, max_results)


def _parse_crossref_response(json_content: str, max_results: int) -> List[Dict]:
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

        authors = []
        for a in item.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            name = f"{given} {family}".strip()
            if name:
                authors.append(name)

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

        container = item.get("container-title", [])
        venue = container[0] if container else ""

        doi = item.get("DOI", "")
        abs_url = item.get("URL", f"https://doi.org/{doi}" if doi else "")

        abstract = _clean_abstract(item.get("abstract", ""))

        citation_count = item.get("is-referenced-by-count", 0) or 0

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
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    return " ".join(clean.split()).strip()
