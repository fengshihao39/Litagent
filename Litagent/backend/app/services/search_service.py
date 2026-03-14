"""Search service orchestrating translation, multi-source retrieval, and normalization."""

import json
import re
import threading
from typing import Any, Dict, List, Optional

from fastapi import UploadFile

from Litagent.backend.app.providers.arxiv import search_papers as arxiv_search
from Litagent.backend.app.providers.crossref import search_papers as crossref_search
from Litagent.backend.app.providers.ieee import search_papers as ieee_search
from Litagent.backend.app.providers.semantic_scholar import (
    search_papers as semantic_search,
)
from Litagent.backend.app.services.llm_service import get_search_queries, is_chinese


def multi_search(
    query: str,
    max_results: int = 10,
    sources: Optional[List[str]] = None,
    year_from: Optional[int] = None,
    use_arxiv_categories: bool = True,
) -> List[Dict]:
    """
    四源并联搜索：arXiv + Semantic Scholar + IEEE Xplore + Crossref
    """
    if sources is None:
        sources = ["arxiv", "semantic_scholar", "ieee", "crossref"]

    per_source = max(max_results, 8)

    results: Dict[str, List[Dict]] = {}
    errors: Dict[str, str] = {}
    lock = threading.Lock()

    def run_arxiv() -> None:
        try:
            papers = arxiv_search(
                query,
                max_results=per_source,
                use_default_categories=use_arxiv_categories,
            )
            for p in papers:
                if "error" not in p:
                    p.setdefault("source", "arxiv")
            with lock:
                results["arxiv"] = papers
        except Exception as e:
            with lock:
                errors["arxiv"] = str(e)

    def run_semantic() -> None:
        try:
            papers = semantic_search(query, max_results=per_source)
            with lock:
                results["semantic_scholar"] = papers
        except Exception as e:
            with lock:
                errors["semantic_scholar"] = str(e)

    def run_ieee() -> None:
        try:
            papers = ieee_search(query, max_results=per_source, start_year=year_from)
            with lock:
                results["ieee"] = papers
        except Exception as e:
            with lock:
                errors["ieee"] = str(e)

    def run_crossref() -> None:
        try:
            papers = crossref_search(query, max_results=per_source, min_year=year_from)
            with lock:
                results["crossref"] = papers
        except Exception as e:
            with lock:
                errors["crossref"] = str(e)

    threads = []
    if "arxiv" in sources:
        threads.append(threading.Thread(target=run_arxiv))
    if "semantic_scholar" in sources:
        threads.append(threading.Thread(target=run_semantic))
    if "ieee" in sources:
        threads.append(threading.Thread(target=run_ieee))
    if "crossref" in sources:
        threads.append(threading.Thread(target=run_crossref))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=25)

    all_papers: List[Dict] = []
    for source in ["semantic_scholar", "arxiv", "crossref", "ieee"]:
        source_papers = results.get(source, [])
        for p in source_papers:
            if "error" not in p:
                all_papers.append(p)

    seen_titles: set = set()
    seen_arxiv_ids: set = set()
    seen_dois: set = set()
    deduped: List[Dict] = []

    for p in all_papers:
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

    if year_from is not None:
        filtered_by_year = []
        for p in deduped:
            py = _get_year(p)
            if py is None or py >= year_from:
                filtered_by_year.append(p)
        deduped = filtered_by_year

    buckets: Dict[str, List[Dict]] = {}
    for p in deduped:
        src = p.get("source", "unknown")
        buckets.setdefault(src, []).append(p)

    final: List[Dict] = []
    source_order = ["semantic_scholar", "arxiv", "crossref", "ieee"]
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


async def search_papers_service(
    query: str,
    file: Optional[UploadFile],
    year_from: Optional[int],
    max_results: int,
    use_domain_vocab: bool,
    use_arxiv_categories: bool,
) -> Dict[str, Any]:
    """Search entry used by API layer."""
    results: List[Dict] = []
    translated_query = query

    if query.strip():
        search_queries = get_search_queries(
            query.strip(),
            use_domain_vocab=use_domain_vocab,
        )
        primary_query = search_queries[0]
        translated_query = primary_query

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

    return {
        "results": deduped,
        "translated_query": translated_query if is_chinese(query) else query,
        "total": len(deduped),
    }


def _normalize(paper: Dict) -> Dict:
    """将 multi_search 返回的字段映射到前端期望的字段"""
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


def _extract_keywords(text: str, n: int = 5) -> List[str]:
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
    freq: Dict[str, int] = {}
    for w in words:
        if w not in stopwords:
            freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq, key=lambda x: freq[x], reverse=True)
    return sorted_words[:n]


async def _parse_upload(file: UploadFile) -> List[Dict]:
    """解析上传的 BibTeX / JSON / CSV 文件"""
    content = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith(".json"):
            return _parse_json(content)
        if filename.endswith(".bib") or filename.endswith(".bibtex"):
            return _parse_bibtex(content.decode("utf-8", errors="ignore"))
        if filename.endswith(".csv"):
            return _parse_csv(content.decode("utf-8", errors="ignore"))
    except Exception:
        pass
    return []


def _parse_json(content: bytes) -> List[Dict]:
    data = json.loads(content)
    if isinstance(data, list):
        return [_normalize_upload(p) for p in data]
    if isinstance(data, dict) and "results" in data:
        return [_normalize_upload(p) for p in data["results"]]
    return []


def _parse_bibtex(text: str) -> List[Dict]:
    """简单解析 BibTeX，提取 title / author / year / journal"""
    papers = []
    entries = re.findall(r"@\w+\{[^@]+\}", text, re.DOTALL)
    for entry in entries:

        def _field(name: str) -> str:
            m = re.search(
                rf"{name}\s*=\s*[{{\"](.*?)[}}\"]", entry, re.IGNORECASE | re.DOTALL
            )
            return m.group(1).strip() if m else ""

        title = _field("title")
        if not title:
            continue
        authors_raw = _field("author")
        authors = [a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()]
        year_str = _field("year")
        year = int(year_str) if year_str.isdigit() else None
        venue = _field("journal") or _field("booktitle") or ""
        doi = _field("doi") or ""

        papers.append(
            {
                "title": title,
                "abstract": _field("abstract") or "",
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


def _parse_csv(text: str) -> List[Dict]:
    """解析 CSV，假设列名包含 title/authors/year/abstract 等"""
    import csv
    import io

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


def _normalize_upload(p: Dict) -> Dict:
    """对上传文件里已有结构化数据做基础标准化"""
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
    """标题标准化，用于去重比较"""
    return title.lower().strip().replace(" ", "").replace("-", "")[:60]


def _get_year(paper: Dict) -> Optional[int]:
    """从论文 dict 中提取发表年份整数，无法获取返回 None"""
    year = paper.get("year")
    if isinstance(year, int):
        return year
    published = paper.get("published", "") or ""
    if published:
        m = re.search(r"(20\d{2}|19\d{2})", str(published))
        if m:
            return int(m.group(1))
    return None
