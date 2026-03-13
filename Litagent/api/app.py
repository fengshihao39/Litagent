"""
星火文献 Agent - FastAPI 后端服务
提供 HTTP 接口供 Streamlit 前端调用

运行方式：
    source venv/bin/activate
    uvicorn xinghuo_agent.api.app:app --host 0.0.0.0 --port 8000 --reload

接口：
    POST /search   搜索论文（关键词 + 可选文件上传 + 年份过滤）
    GET  /health   健康检查
"""

import json
import re
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from Litagent.services.query.query_translator import get_search_queries, is_chinese
from Litagent.services.search.multi_search import multi_search

app = FastAPI(
    title="星火文献 Agent API",
    description="西安电子科技大学 · 第37届星火杯参赛项目",
    version="2.0.0",
)

# 允许前端跨域访问（Streamlit 和 FastAPI 端口不同）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 健康检查 ─────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "星火文献 Agent", "version": "2.0.0"}


# ── 主搜索接口 ───────────────────────────────────────────
@app.post("/search")
async def search(
    query: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
    year_from: Optional[int] = Form(default=None),
    max_results: int = Form(default=10),
    use_domain_vocab: bool = Form(default=True),
    use_arxiv_categories: bool = Form(default=True),
) -> Dict[str, Any]:
    """
    搜索论文接口

    参数：
        query       - 关键词（支持中英文）
        file        - 可选，上传的 BibTeX/JSON/CSV 文件（解析后合并到结果）
        year_from   - 可选，最早发表年份过滤（如 2020）
        max_results - 返回数量，默认 10

    返回：
        {
          "results": [ {title, abstract, authors, year, keywords, venue, doi, ...} ],
          "translated_query": str,   # 若输入为中文，返回翻译后的英文查询
          "total": int
        }
    """
    results: List[Dict] = []
    translated_query = query

    # 1. 关键词搜索（多源并联）
    if query.strip():
        # 查询翻译（中文 → 英文）
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

    # 2. 文件解析（若上传了文件）
    if file is not None:
        file_papers = await _parse_upload(file)
        results.extend(file_papers)

    # 3. 去重（按标题）
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


# ── 字段标准化：把后端格式转成前端期望格式 ───────────────
def _normalize(paper: Dict) -> Dict:
    """将 multi_search 返回的字段映射到前端期望的字段"""

    # year: 从 "2024-01-15" 或 "2024" 中提取整数
    published = paper.get("published", "") or ""
    year_match = re.match(r"(\d{4})", published)
    year = int(year_match.group(1)) if year_match else None

    # keywords: 优先用 categories，没有就从摘要粗提
    categories = paper.get("categories", []) or []
    keywords = [c for c in categories if c] if categories else []
    if not keywords:
        keywords = _extract_keywords(paper.get("summary", ""))

    # venue: S2 有，arXiv 没有就标注来源
    source = paper.get("source", "")
    venue = paper.get("venue", "") or ""
    if not venue:
        venue = {
            "arxiv": "arXiv",
            "semantic_scholar": "Semantic Scholar",
            "ieee": "IEEE",
        }.get(source, "arXiv")

    # doi: S2 有 doi，arXiv 用 arxiv_id 凑
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
    """从摘要中粗提关键词（停用词过滤 + 高频名词）"""
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


# ── 文件解析 ─────────────────────────────────────────────
async def _parse_upload(file: UploadFile) -> List[Dict]:
    """解析上传的 BibTeX / JSON / CSV 文件"""
    content = await file.read()
    filename = file.filename or ""

    try:
        if filename.endswith(".json"):
            return _parse_json(content)
        elif filename.endswith(".bib") or filename.endswith(".bibtex"):
            return _parse_bibtex(content.decode("utf-8", errors="ignore"))
        elif filename.endswith(".csv"):
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
    import csv, io

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
