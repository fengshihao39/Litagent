"""
Litagent - 多源并联搜索服务
"""

import csv
import io
import json
import re
import threading

from fastapi import UploadFile

from Litagent.backend.app.models.response import SearchResponse
from Litagent.backend.app.providers.arxiv import search_papers as arxiv_search
from Litagent.backend.app.providers.crossref import search_papers as crossref_search
from Litagent.backend.app.providers.ieee import search_papers as ieee_search
from Litagent.backend.app.providers.semantic_scholar import (
    search_papers as semantic_search,
)
from Litagent.backend.app.services.llm_service import get_search_queries


def _search_arxiv(
    query: str,
    per_source: int,
    use_arxiv_categories: bool,
) -> list[dict]:
    papers = arxiv_search(
        query,
        max_results=per_source,
        use_default_categories=use_arxiv_categories,
    )
    for p in papers:
        if "error" not in p:
            p.setdefault("source", "arxiv")
    return papers


def _search_semantic(query: str, per_source: int) -> list[dict]:
    return semantic_search(query, max_results=per_source)


def _search_ieee(
    query: str,
    per_source: int,
    year_from: int | None,
) -> list[dict]:
    return ieee_search(query, max_results=per_source, start_year=year_from)


def _search_crossref(
    query: str,
    per_source: int,
    year_from: int | None,
) -> list[dict]:
    return crossref_search(query, max_results=per_source, min_year=year_from)


def _run_parallel_search(
    query: str,
    per_source: int,
    year_from: int | None,
    use_arxiv_categories: bool,
    sources: list[str],
) -> dict[str, list[dict]]:
    lock = threading.Lock()
    results: dict[str, list[dict]] = {}

    def run_source(source: str, fn) -> None:
        try:
            papers = fn()
        except (ValueError, TypeError, RuntimeError):
            papers = []
        with lock:
            results[source] = papers

    source_map = {
        "arxiv": lambda: _search_arxiv(query, per_source, use_arxiv_categories),
        "semantic_scholar": lambda: _search_semantic(query, per_source),
        "ieee": lambda: _search_ieee(query, per_source, year_from),
        "crossref": lambda: _search_crossref(query, per_source, year_from),
    }

    threads = [
        threading.Thread(target=run_source, args=(src, source_map[src]))
        for src in sources
        if src in source_map
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=25)

    return results


def _collect_papers(
    results: dict[str, list[dict]], source_order: list[str]
) -> list[dict]:
    all_papers: list[dict] = []
    for source in source_order:
        for p in results.get(source, []):
            if "error" not in p:
                all_papers.append(p)
    return all_papers


def _dedupe_papers(papers: list[dict]) -> list[dict]:
    seen_titles: set = set()
    seen_arxiv_ids: set = set()
    seen_dois: set = set()
    deduped: list[dict] = []

    for p in papers:
        arxiv_id = p.get("arxiv_id", "")
        doi = p.get("doi", "")
        title_key = _normalize_title(p.get("title", ""))

        if arxiv_id and arxiv_id in seen_arxiv_ids:
            continue
        if doi and doi in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue

        if arxiv_id:
            seen_arxiv_ids.add(arxiv_id)
        if doi:
            seen_dois.add(doi)
        if title_key:
            seen_titles.add(title_key)

        deduped.append(p)

    return deduped


def _filter_by_year(papers: list[dict], year_from: int | None) -> list[dict]:
    if year_from is None:
        return papers

    filtered: list[dict] = []
    for p in papers:
        py = _get_year(p)
        if py is None or py >= year_from:
            filtered.append(p)
    return filtered


def _bucket_by_source(papers: list[dict]) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for p in papers:
        src = p.get("source", "unknown")
        buckets.setdefault(src, []).append(p)
    return buckets


def _round_robin_pick(
    buckets: dict[str, list[dict]],
    source_order: list[str],
    max_results: int,
) -> list[dict]:
    final: list[dict] = []
    while len(final) < max_results:
        added = False
        for src in source_order:
            if len(final) >= max_results:
                break
            if buckets.get(src):
                final.append(buckets[src].pop(0))
                added = True
        if not added:
            break
    return final


def multi_search(
    query: str,
    max_results: int = 10,
    sources: list[str] | None = None,
    year_from: int | None = None,
    use_arxiv_categories: bool = True,
) -> list[dict]:
    """多源并联搜索服务。

    Args:
        query (str): 用户的查询关键词。
        max_results (int, optional): 最大返回结果数. Defaults to 10.
        sources (Optional[List[str]], optional): 指定的查询源. Defaults to None.
        year_from (Optional[int], optional): 查询文献年份的最早值. Defaults to None.
        use_arxiv_categories (bool, optional): 是否在 arXiv 中限定分类. Defaults to True.

    Returns:
        List[Dict]: 返回搜索结果。
    """

    if sources is None:
        sources = ["arxiv", "semantic_scholar", "ieee", "crossref"]

    per_source = max(max_results, 8)
    source_order = ["semantic_scholar", "arxiv", "crossref", "ieee"]

    results = _run_parallel_search(
        query=query,
        per_source=per_source,
        year_from=year_from,
        use_arxiv_categories=use_arxiv_categories,
        sources=sources,
    )
    all_papers = _collect_papers(results, source_order)
    deduped = _dedupe_papers(all_papers)
    deduped = _filter_by_year(deduped, year_from)
    buckets = _bucket_by_source(deduped)

    return _round_robin_pick(buckets, source_order, max_results)


async def search_papers_service(
    query: str,
    file: UploadFile | None,
    year_from: int | None,
    max_results: int,
    use_arxiv_categories: bool,
) -> SearchResponse:
    """Search entry used by API layer."""
    results: list[dict] = []

    if query.strip():
        search_queries = get_search_queries(query.strip())
        primary_query = search_queries[0]

        raw_papers = multi_search(
            primary_query,
            max_results=max_results,
            year_from=year_from,
            use_arxiv_categories=use_arxiv_categories,
        )
        for p in raw_papers:
            if "error" not in p:
                results.append(_normalize(p))

    if file is not None:
        file_papers = await _parse_upload(file)
        results.extend(file_papers)

    seen = set()
    deduped = []
    for p in results:
        key = p["title"].lower().strip()[:60]
        if key not in seen:
            seen.add(key)
            deduped.append(p)

    return SearchResponse(
        results=deduped,
        total=len(deduped),
    )


def _normalize(paper: dict) -> dict:
    published = paper.get("published", "") or ""
    year_match = re.match(r"(\d{4})", published)
    year = int(year_match.group(1)) if year_match else None

    categories = paper.get("categories", []) or []
    keywords = [c for c in categories if c] if categories else []
    if not keywords:
        keywords = _extract_keywords(paper.get("summary", ""))

    source = paper.get("source", "")
    venue = paper.get("venue", "") or ""
    if not venue:
        venue = {
            "arxiv": "arXiv",
            "semantic_scholar": "Semantic Scholar",
            "ieee": "IEEE",
        }.get(source, "arXiv")

    doi = paper.get("doi", "") or ""
    if not doi and paper.get("arxiv_id"):
        doi = f"arXiv:{paper['arxiv_id']}"

    return {
        "title": paper.get("title", ""),
        "abstract": paper.get("summary", ""),
        "authors": paper.get("authors", []),
        "year": year,
        "keywords": keywords,
        "venue": venue,
        "doi": doi,
        "source": source,
        "abs_url": paper.get("abs_url", ""),
        "citation_count": paper.get("citation_count", 0),
        "tldr": paper.get("tldr", ""),
    }


def _extract_keywords(text: str, n: int = 5) -> list[str]:
    stopwords = {
        "the",
        "a",
        "an",
        "of",
        "in",
        "for",
        "and",
        "or",
        "to",
        "with",
        "is",
        "are",
        "we",
        "our",
        "this",
        "that",
        "on",
        "by",
        "from",
        "which",
        "be",
        "as",
        "at",
        "its",
        "it",
        "also",
        "can",
        "not",
        "have",
        "has",
        "been",
        "more",
        "than",
        "using",
        "used",
        "based",
    }
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in stopwords:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq, key=lambda x: freq[x], reverse=True)
    return sorted_words[:n]


async def _parse_upload(file: UploadFile) -> list[dict]:
    content = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith(".json"):
            return _parse_json(content)
        if filename.endswith(".bib") or filename.endswith(".bibtex"):
            return _parse_bibtex(content.decode("utf-8", errors="ignore"))
        if filename.endswith(".csv"):
            return _parse_csv(content.decode("utf-8", errors="ignore"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    return []


def _parse_json(content: bytes) -> list[dict]:
    data = json.loads(content)
    if isinstance(data, list):
        return [_normalize_upload(p) for p in data]
    if isinstance(data, dict) and "results" in data:
        return [_normalize_upload(p) for p in data["results"]]
    return []


def _parse_bibtex(text: str) -> list[dict]:
    papers = []
    entries = re.findall(r"@\w+\{[^@]+\}", text, re.DOTALL)

    def _field(entry_text: str, name: str) -> str:
        m = re.search(
            rf"{name}\s*=\s*[{{\"](.*?)[}}\"]",
            entry_text,
            re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else ""

    for entry in entries:
        title = _field(entry, "title")
        if not title:
            continue
        authors_raw = _field(entry, "author")
        authors = [a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()]
        year_str = _field(entry, "year")
        year = int(year_str) if year_str.isdigit() else None
        venue = _field(entry, "journal") or _field(entry, "booktitle") or ""
        doi = _field(entry, "doi") or ""

        papers.append(
            {
                "title": title,
                "abstract": _field(entry, "abstract") or "",
                "authors": authors,
                "year": year,
                "keywords": [],
                "venue": venue,
                "doi": doi,
                "source": "upload",
                "abs_url": "",
                "citation_count": 0,
                "tldr": "",
            }
        )
    return papers


def _parse_csv(text: str) -> list[dict]:
    papers = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        title = row.get("title") or row.get("Title") or ""
        if not title:
            continue
        authors_raw = row.get("authors") or row.get("Authors") or ""
        authors = [a.strip() for a in authors_raw.split(";") if a.strip()]
        year_str = row.get("year") or row.get("Year") or ""
        year = int(year_str) if str(year_str).isdigit() else None
        papers.append(
            {
                "title": title,
                "abstract": row.get("abstract") or row.get("Abstract") or "",
                "authors": authors,
                "year": year,
                "keywords": [],
                "venue": row.get("venue") or row.get("journal") or "",
                "doi": row.get("doi") or row.get("DOI") or "",
                "source": "upload",
                "abs_url": "",
                "citation_count": 0,
                "tldr": "",
            }
        )
    return papers


def _normalize_upload(p: dict) -> dict:
    year = p.get("year")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    return {
        "title": p.get("title", ""),
        "abstract": p.get("abstract") or p.get("summary", ""),
        "authors": p.get("authors", []),
        "year": year,
        "keywords": p.get("keywords", []),
        "venue": p.get("venue", ""),
        "doi": p.get("doi", ""),
        "source": "upload",
        "abs_url": p.get("abs_url", ""),
        "citation_count": p.get("citation_count", 0),
        "tldr": p.get("tldr", ""),
    }


def _normalize_title(title: str) -> str:
    return title.lower().strip().replace(" ", "").replace("-", "")[:60]


def _get_year(paper: dict) -> int | None:
    year = paper.get("year")
    if isinstance(year, int):
        return year
    published = paper.get("published", "") or ""
    if published:
        m = re.search(r"(20\d{2}|19\d{2})", str(published))
        if m:
            return int(m.group(1))
    return None
