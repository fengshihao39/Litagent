"""
IEEE Xplore 搜索模块
使用 Metadata Search API
Key 状态 waiting 时会返回 403，激活后自动生效
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from ..core.config import get_ieee_api_key
from .base import ProviderBase


IEEE_API_BASE = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
IEEE_API_KEY = get_ieee_api_key(required=False)


class IeeeProvider(ProviderBase):
    name = "ieee"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> List[Dict]:
        return search_papers(
            query,
            max_results=max_results,
            start_year=start_year,
            end_year=end_year,
        )


def search_papers(
    query: str,
    max_results: int = 8,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> List[Dict]:
    """使用 IEEE Xplore Metadata Search API 搜索论文"""
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
                    "error": "IEEE API Key 尚未激活（状态 waiting），请等待审核通过后再试。",
                    "source": "ieee",
                }
            ]
        if e.code == 429:
            return [
                {
                    "error": "IEEE API 今日调用次数已达上限（200次/天）。",
                    "source": "ieee",
                }
            ]
        return [
            {
                "error": f"IEEE API 请求失败 HTTP {e.code}: {e.reason}",
                "source": "ieee",
            }
        ]
    except Exception as e:
        return [{"error": f"IEEE 网络请求失败: {e}", "source": "ieee"}]

    return _parse_response(content)


def _parse_response(json_content: str) -> List[Dict]:
    """解析 IEEE API 返回的 JSON"""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"IEEE 响应解析失败: {e}", "source": "ieee"}]

    articles = data.get("articles", [])
    if not articles:
        return []

    papers = []
    for a in articles:
        title = a.get("title", "").strip()
        abstract = a.get("abstract", "").strip()

        if not title:
            continue

        authors_data = a.get("authors", {}).get("authors", [])
        authors = [
            auth.get("full_name", "") for auth in authors_data if auth.get("full_name")
        ]

        pub_year = str(a.get("publication_year") or "")
        published = f"{pub_year}-01-01" if pub_year else "unknown"

        venue = a.get("publication_title", "")
        doi = a.get("doi", "")
        article_number = a.get("article_number", "")
        abs_url = a.get("html_url") or (
            f"https://ieeexplore.ieee.org/document/{article_number}"
            if article_number
            else ""
        )
        pdf_url = a.get("pdf_url", "")

        kw_data = a.get("index_terms", {})
        keywords = []
        for kw_group in kw_data.values():
            keywords.extend(kw_group.get("terms", []))

        papers.append(
            {
                "source": "ieee",
                "paper_id": article_number,
                "arxiv_id": "",
                "doi": doi,
                "title": title,
                "authors": authors,
                "published": published,
                "year": pub_year,
                "venue": venue,
                "categories": keywords[:5],
                "summary": abstract,
                "tldr": "",
                "citation_count": 0,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )

    return papers
