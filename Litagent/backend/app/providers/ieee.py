"""
Litagent - FastAPI 后端 IEEE 搜索接口
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from Litagent.backend.app.core.config import get_ieee_api_key
from Litagent.backend.app.providers.base import ProviderBase

IEEE_API_BASE = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
IEEE_API_KEY = get_ieee_api_key(required=False)


class IeeeProvider(ProviderBase):
    """IEEE provider 封装。"""

    name = "ieee"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[dict]:
        return search_papers(
            query,
            max_results=max_results,
            start_year=start_year,
            end_year=end_year,
        )


def search_papers(
    query: str,
    max_results: int = 8,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict]:
    """在 IEEE 上搜索文献。

    Args:
        query (str): 搜索关键词。
        max_results (int, optional): 搜索返回的最大数量. Defaults to 8.
        start_year (Optional[int], optional): 返回文献的最早年份. Defaults to None.
        end_year (Optional[int], optional): 返回文献的最晚年份. Defaults to None.

    Returns:
        List[Dict]: 返回搜索到的文献或报错信息。
    """

    # why Claude generate code like this...

    if not IEEE_API_KEY:
        return [
            {
                "error": "IEEE API Key 未配置，请在 .env 中设置 IEEE_API_KEY。",
                "source": "ieee",
            }
        ]

    params = {
        "apikey": IEEE_API_KEY,
        "querytext": query,
        "max_records": min(max_results, 25),
        "start_record": 1,
        "sort_order": "desc",
        "sort_field": "article_number",
        "format": "json",
    }

    if start_year:
        params["start_year"] = start_year
    if end_year:
        params["end_year"] = end_year

    url = f"{IEEE_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return [
                {
                    "error": "IEEE API Key 尚未激活，请等待审核通过后再试。",
                    "source": "ieee",
                }
            ]
        if e.code == 429:
            return [
                {
                    "error": "IEEE API 今日调用次数已达上限。",
                    "source": "ieee",
                }
            ]
        return [
            {
                "error": f"IEEE API 错误 {e.code}: {e}",
                "source": "ieee",
            }
        ]
    except (urllib.error.URLError, TimeoutError) as e:
        return [{"error": f"IEEE 网络请求失败: {e}", "source": "ieee"}]

    return _parse_ieee_response(content)


def _extract_ieee_authors(article: dict) -> list[str]:
    authors_data = article.get("authors", {}).get("authors", [])
    return [auth.get("full_name", "") for auth in authors_data if auth.get("full_name")]


def _extract_ieee_keywords(article: dict) -> list[str]:
    kw_data = article.get("index_terms", {})
    keywords = []
    for kw_group in kw_data.values():
        keywords.extend(kw_group.get("terms", []))
    return keywords


def _extract_ieee_abs_url(article: dict, article_number: str) -> str:
    return article.get("html_url") or (
        f"https://ieeexplore.ieee.org/document/{article_number}"
        if article_number
        else ""
    )


def _parse_ieee_article(article: dict) -> dict | None:
    title = article.get("title", "").strip()
    if not title:
        return None

    pub_year = str(article.get("publication_year") or "")
    article_number = article.get("article_number", "")

    return {
        "source": "ieee",
        "paper_id": article_number,
        "arxiv_id": "",
        "doi": article.get("doi", ""),
        "title": title,
        "authors": _extract_ieee_authors(article),
        "published": f"{pub_year}-01-01" if pub_year else "unknown",
        "year": pub_year,
        "venue": article.get("publication_title", ""),
        "categories": _extract_ieee_keywords(article)[:5],
        "summary": article.get("abstract", "").strip(),
        "tldr": "",
        "citation_count": 0,
        "pdf_url": article.get("pdf_url", ""),
        "abs_url": _extract_ieee_abs_url(article, article_number),
    }


def _parse_ieee_response(json_content: str) -> list[dict]:
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"IEEE 响应解析失败: {e}", "source": "ieee"}]

    articles = data.get("articles", [])
    if not articles:
        return []

    papers: list[dict] = []
    for article in articles:
        parsed = _parse_ieee_article(article)
        if parsed:
            papers.append(parsed)

    return papers
