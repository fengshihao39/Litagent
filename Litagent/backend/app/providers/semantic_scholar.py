"""
Semantic Scholar 论文搜索模块
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .base import ProviderBase


SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarProvider(ProviderBase):
    name = "semantic_scholar"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        fields_of_study: Optional[List[str]] = None,
        min_citations: int = 0,
        sort_by: str = "relevance",
    ) -> List[Dict]:
        return search_papers(
            query,
            max_results=max_results,
            fields_of_study=fields_of_study,
            min_citations=min_citations,
            sort_by=sort_by,
        )


def search_papers(
    query: str,
    max_results: int = 8,
    fields_of_study: Optional[List[str]] = None,
    min_citations: int = 0,
    sort_by: str = "relevance",
) -> List[Dict]:
    """使用 Semantic Scholar API 搜索论文"""
    fields = ",".join(
        [
            "paperId",
            "externalIds",
            "title",
            "abstract",
            "authors",
            "year",
            "publicationDate",
            "venue",
            "publicationVenue",
            "citationCount",
            "referenceCount",
            "openAccessPdf",
            "fieldsOfStudy",
            "tldr",
        ]
    )

    params = {
        "query": query,
        "limit": min(max_results * 2, 50),
        "fields": fields,
    }

    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": "StarfireAgent/1.0 (mailto:25209100302@stu.xidian.edu.cn)",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(3)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as response:
                    content = response.read().decode("utf-8")
            except urllib.error.HTTPError as e2:
                return [
                    {
                        "error": f"Semantic Scholar 限流(429)，请稍后重试: {e2}",
                        "source": "semantic_scholar",
                    }
                ]
            except Exception as e2:
                return [
                    {
                        "error": f"Semantic Scholar 请求失败: {e2}",
                        "source": "semantic_scholar",
                    }
                ]
        else:
            return [
                {
                    "error": f"Semantic Scholar API 错误 {e.code}: {e}",
                    "source": "semantic_scholar",
                }
            ]
    except Exception as e:
        return [
            {
                "error": f"Semantic Scholar 网络请求失败: {e}",
                "source": "semantic_scholar",
            }
        ]

    return _parse_semantic_response(content, max_results, min_citations, sort_by)


def _parse_semantic_response(
    json_content: str,
    max_results: int,
    min_citations: int,
    sort_by: str,
) -> List[Dict]:
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"响应解析失败: {e}", "source": "semantic_scholar"}]

    raw_papers = data.get("data", [])
    if not raw_papers:
        return []

    papers = []
    for p in raw_papers:
        abstract = p.get("abstract") or ""
        if not abstract.strip():
            continue

        title = p.get("title") or ""
        if not title.strip():
            continue

        citation_count = p.get("citationCount") or 0
        if citation_count < min_citations:
            continue

        authors = [a.get("name", "") for a in p.get("authors", []) if a.get("name")]

        pub_date = p.get("publicationDate") or ""
        year = str(p.get("year") or "")
        if pub_date:
            published = pub_date[:10]
        elif year:
            published = f"{year}-01-01"
        else:
            published = "unknown"

        venue = ""
        pub_venue = p.get("publicationVenue")
        if pub_venue:
            venue = pub_venue.get("name", "") or p.get("venue", "")
        else:
            venue = p.get("venue", "")

        external_ids = p.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv", "")
        doi = external_ids.get("DOI", "")
        paper_id = p.get("paperId", "")

        if arxiv_id:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        elif doi:
            abs_url = f"https://doi.org/{doi}"
            pdf_url = ""
        else:
            abs_url = f"https://www.semanticscholar.org/paper/{paper_id}"
            pdf_url = ""

        open_pdf = p.get("openAccessPdf")
        if open_pdf and open_pdf.get("url"):
            pdf_url = open_pdf["url"]

        tldr = ""
        tldr_obj = p.get("tldr")
        if tldr_obj and tldr_obj.get("text"):
            tldr = tldr_obj["text"]

        fields = p.get("fieldsOfStudy") or []

        papers.append(
            {
                "source": "semantic_scholar",
                "paper_id": paper_id,
                "arxiv_id": arxiv_id,
                "doi": doi,
                "title": title,
                "authors": authors,
                "published": published,
                "year": year,
                "venue": venue,
                "categories": fields,
                "summary": abstract,
                "tldr": tldr,
                "citation_count": citation_count,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )

    if sort_by == "citationCount":
        papers.sort(key=lambda x: x.get("citation_count", 0), reverse=True)

    return papers[:max_results]
