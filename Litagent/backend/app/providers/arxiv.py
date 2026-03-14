"""
Litagent - FastAPI 后端 arXiv 搜索接口
"""

import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from Litagent.backend.app.providers.base import ProviderBase

XIDIAN_CATEGORIES = {
    "人工智能": ["cs.AI", "cs.LG", "cs.CV", "cs.CL"],
    "电子信息": ["eess.SP", "eess.IV", "eess.AS", "cs.IT"],
    "雷达信号处理": ["eess.SP", "cs.IT", "eess.SY"],
}

DEFAULT_CATEGORIES = list({cat for cats in XIDIAN_CATEGORIES.values() for cat in cats})

ARXIV_API_BASE = "https://export.arxiv.org/api/query"


class ArxivProvider(ProviderBase):
    """arXiv provider 封装。"""

    name = "arxiv"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        categories: list[str] | None = None,
        use_default_categories: bool = True,
        sort_by: str = "relevance",
    ) -> list[dict]:
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
    categories: list[str] | None = None,
    use_default_categories: bool = True,
    sort_by: str = "relevance",
) -> list[dict]:
    """在 arXiv 上搜索文献。

    Args:
        query (str): 搜索关键词。
        max_results (int, optional): 搜索返回的最大数量. Defaults to 8.
        categories (Optional[List[str]], optional): 文献的分类. Defaults to None.
        use_default_categories (bool, optional): 是否使用默认的分类对文献进行筛选. Defaults to True.
        sort_by (str, optional): 文献的排序方法. Defaults to "relevance".

    Returns:
        List[Dict]: 返回搜索到的文献或报错信息。
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
    except urllib.error.HTTPError as e:
        return [{"error": f"arXiv API 错误 {e.code}: {e}", "source": "arXiv"}]
    except (urllib.error.URLError, TimeoutError) as e:
        return [{"error": f"arXiv API 网络请求失败: {e}", "source": "arXiv"}]

    return _parse_arxiv_response(content)


def _get_entry_text(entry: ET.Element, tag: str, ns: dict[str, str]) -> str:
    el = entry.find(tag, ns)
    return (el.text or "").strip() if el is not None else ""


def _parse_arxiv_entry(entry: ET.Element, ns: dict[str, str]) -> dict:
    raw_id = _get_entry_text(entry, "atom:id", ns)
    arxiv_id = raw_id.split("/abs/")[-1].split("v")[0]
    title = " ".join(_get_entry_text(entry, "atom:title", ns).split())
    summary = " ".join(_get_entry_text(entry, "atom:summary", ns).split())

    authors = []
    for author in entry.findall("atom:author", ns):
        name_el = author.find("atom:name", ns)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    published = _get_entry_text(entry, "atom:published", ns)[:10]
    updated = _get_entry_text(entry, "atom:updated", ns)[:10]
    categories = [tag.get("term", "") for tag in entry.findall("atom:category", ns)]

    return {
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


def _parse_arxiv_response(xml_content: str) -> list[dict]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    root = ET.fromstring(xml_content)
    return [_parse_arxiv_entry(entry, ns) for entry in root.findall("atom:entry", ns)]
