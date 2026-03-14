"""
arXiv 论文搜索工具
支持按关键词、领域分类搜索，默认聚焦电子信息/AI/雷达方向
"""

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from .base import ProviderBase


XIDIAN_CATEGORIES = {
    "人工智能": ["cs.AI", "cs.LG", "cs.CV", "cs.CL"],
    "电子信息": ["eess.SP", "eess.IV", "eess.AS", "cs.IT"],
    "雷达信号处理": ["eess.SP", "cs.IT", "eess.SY"],
}

DEFAULT_CATEGORIES = list({cat for cats in XIDIAN_CATEGORIES.values() for cat in cats})

ARXIV_API_BASE = "https://export.arxiv.org/api/query"


class ArxivProvider(ProviderBase):
    name = "arxiv"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        categories: Optional[List[str]] = None,
        use_default_categories: bool = True,
        sort_by: str = "relevance",
    ) -> List[Dict]:
        return search_papers(
            query,
            max_results=max_results,
            categories=categories,
            use_default_categories=use_default_categories,
            sort_by=sort_by,
        )


def search_papers(
    query: str,
    max_results: int = 8,
    categories: Optional[List[str]] = None,
    use_default_categories: bool = True,
    sort_by: str = "relevance",
) -> List[Dict]:
    """
    搜索 arXiv 论文
    """
    if categories is None:
        categories = DEFAULT_CATEGORIES if use_default_categories else []

    if categories:
        cat_filter = " OR ".join([f"cat:{c}" for c in categories])
        search_query = f"({query}) AND ({cat_filter})"
    else:
        search_query = f"({query})"

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
