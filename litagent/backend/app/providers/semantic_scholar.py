"""
Litagent - FastAPI 后端 Semantic Scholar 搜索接口
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from litagent.backend.app.providers.base import ProviderBase

SEMANTIC_SCHOLAR_API_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarProvider(ProviderBase):
    """Semantic Scholar provider 封装。"""

    name = "semantic_scholar"

    def search_papers(
        self,
        query: str,
        max_results: int = 8,
        fields_of_study: list[str] | None = None,
        min_citations: int = 0,
        sort_by: str = "relevance",
    ) -> list[dict]:
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
    fields_of_study: list[str] | None = None,
    min_citations: int = 0,
    sort_by: str = "relevance",
) -> list[dict]:
    """在 Semantic Scholar 上搜索文献。

    Args:
        query (str): 搜索关键词。
        max_results (int, optional): 搜索返回的最大数量. Defaults to 8.
        fields_of_study (Optional[List[str]], optional): 文献的研究领域. Defaults to None.
        min_citations (int, optional): 文献的最小引用数量. Defaults to 0.
        sort_by (str, optional): 文献的排序方法. Defaults to "relevance".

    Returns:
        List[Dict]: 返回搜索到的文献或报错信息。
    """

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

    url = f"{SEMANTIC_SCHOLAR_API_BASE}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": "StarfireAgent/1.0 (mailto:25209100302@stu.xidian.edu.cn)",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return [
                {
                    "error": "Semantic Scholar 接口可能被限流。",
                    "source": "semantic_scholar",
                }
            ]
        return [
            {
                "error": f"Semantic Scholar 错误: {e}",
                "source": "semantic_scholar",
            }
        ]
    except (urllib.error.URLError, TimeoutError) as e:
        return [
            {
                "error": f"Semantic Scholar 网络请求失败: {e}",
                "source": "semantic_scholar",
            }
        ]

    return _parse_semantic_scholar_response(
        content, max_results, min_citations, sort_by
    )


def _parse_semantic_scholar_response(
    json_content: str,
    max_results: int,
    min_citations: int,
    sort_by: str,
) -> list[dict]:
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [
            {
                "error": f"Semantic Scholar 响应解析失败: {e}",
                "source": "semantic_scholar",
            }
        ]

    raw_papers = data.get("data", [])
    if not raw_papers:
        return []

    papers: list[dict] = []
    for paper in raw_papers:
        parsed = _parse_semantic_scholar_paper(paper, min_citations)
        if parsed:
            papers.append(parsed)

    if sort_by == "citationCount":
        papers.sort(key=lambda x: x.get("citation_count", 0), reverse=True)

    return papers[:max_results]


def _parse_semantic_scholar_paper(paper: dict, min_citations: int) -> dict | None:
    abstract = (paper.get("abstract") or "").strip()
    if not abstract:
        return None

    title = (paper.get("title") or "").strip()
    if not title:
        return None

    citation_count = paper.get("citationCount") or 0
    if citation_count < min_citations:
        return None

    publication_date = _format_semantic_scholar_date(paper)
    venue = _extract_semantic_scholar_venue(paper)
    external_ids = paper.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv", "")
    doi = external_ids.get("DOI", "")
    paper_id = paper.get("paperId", "")
    abs_url, pdf_url = _extract_semantic_scholar_urls(paper, paper_id, arxiv_id, doi)

    return {
        "source": "semantic_scholar",
        "paper_id": paper_id,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "title": title,
        "authors": _extract_semantic_scholar_authors(paper),
        "published": publication_date,
        "year": str(paper.get("year") or ""),
        "venue": venue,
        "categories": paper.get("fieldsOfStudy") or [],
        "summary": abstract,
        "tldr": _extract_semantic_scholar_tldr(paper),
        "citation_count": citation_count,
        "pdf_url": pdf_url,
        "abs_url": abs_url,
    }


def _extract_semantic_scholar_authors(paper: dict) -> list[str]:
    return [a.get("name", "") for a in paper.get("authors", []) if a.get("name")]


def _format_semantic_scholar_date(paper: dict) -> str:
    pub_date = paper.get("publicationDate") or ""
    year = str(paper.get("year") or "")
    if pub_date:
        return pub_date[:10]
    if year:
        return f"{year}-01-01"
    return "unknown"


def _extract_semantic_scholar_venue(paper: dict) -> str:
    pub_venue = paper.get("publicationVenue")
    if pub_venue:
        return pub_venue.get("name", "") or paper.get("venue", "")
    return paper.get("venue", "")


def _extract_semantic_scholar_urls(
    paper: dict,
    paper_id: str,
    arxiv_id: str,
    doi: str,
) -> tuple[str, str]:
    if arxiv_id:
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    elif doi:
        abs_url = f"https://doi.org/{doi}"
        pdf_url = ""
    else:
        abs_url = f"https://www.semanticscholar.org/paper/{paper_id}"
        pdf_url = ""

    open_pdf = paper.get("openAccessPdf")
    if open_pdf and open_pdf.get("url"):
        pdf_url = open_pdf["url"]

    return abs_url, pdf_url


def _extract_semantic_scholar_tldr(paper: dict) -> str:
    tldr_obj = paper.get("tldr")
    if tldr_obj and tldr_obj.get("text"):
        return tldr_obj["text"]
    return ""
