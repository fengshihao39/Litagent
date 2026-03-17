"""
Litagent - 施引文献服务

策略：
  1. 优先 Semantic Scholar Graph API /paper/{id}/citations
  2. 限流 / 查不到时返回空列表，绝不造假
"""

from __future__ import annotations

import time
import requests

_SS_BASE = "https://api.semanticscholar.org/graph/v1"
_EMAIL = "25209100302@stu.xidian.edu.cn"


def _ss_headers() -> dict:
    return {"User-Agent": f"Litagent/1.0 (mailto:{_EMAIL})"}


def _fetch_ss_id(paper: dict) -> str | None:
    """从 paper 字段中解析或查询 Semantic Scholar paper ID。"""
    ss_id = (paper.get("ss_paper_id") or "").strip()
    if ss_id:
        return ss_id

    doi = (paper.get("doi") or "").strip()
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    title = (paper.get("title") or "").strip()

    def _get(url: str, params: dict) -> str | None:
        try:
            resp = requests.get(url, params=params, headers=_ss_headers(), timeout=10)
            if resp.status_code in (404, 429):
                return None
            resp.raise_for_status()
            return resp.json().get("paperId")
        except Exception:
            return None

    if doi:
        pid = _get(f"{_SS_BASE}/paper/DOI:{doi}", {"fields": "paperId"})
        if pid:
            return pid
        time.sleep(0.5)

    if arxiv_id:
        pid = _get(f"{_SS_BASE}/paper/arXiv:{arxiv_id}", {"fields": "paperId"})
        if pid:
            return pid
        time.sleep(0.5)

    if title:
        try:
            resp = requests.get(
                f"{_SS_BASE}/paper/search",
                params={"query": title, "fields": "paperId", "limit": 1},
                headers=_ss_headers(),
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or []
                if data:
                    return data[0].get("paperId")
        except Exception:
            pass

    return None


def _normalize_citation(raw: dict) -> dict:
    """把 Semantic Scholar citations 条目统一成我们的格式。"""
    citing = raw.get("citingPaper") or {}
    ext_ids = citing.get("externalIds") or {}
    doi = ext_ids.get("DOI") or ""
    arxiv_id = ext_ids.get("ArXiv") or ""
    return {
        "title": citing.get("title") or "",
        "authors": [a.get("name", "") for a in (citing.get("authors") or [])],
        "year": citing.get("year"),
        "venue": citing.get("venue") or "",
        "doi": doi,
        "arxiv_id": arxiv_id,
        "ss_paper_id": citing.get("paperId") or "",
        "citation_count": citing.get("citationCount"),
        "abs_url": (
            f"https://arxiv.org/abs/{arxiv_id}"
            if arxiv_id
            else (f"https://doi.org/{doi}" if doi else "")
        ),
    }


def get_citations(paper: dict, limit: int = 20) -> dict:
    """
    获取施引文献列表。

    Args:
        paper: 包含 doi / arxiv_id / ss_paper_id / title 等字段的论文字典
        limit: 最多返回条数（默认 20）

    Returns:
        {
          "citations": list[dict],
          "source": "semantic_scholar" | "unavailable",
          "total": int,
        }
    """
    ss_paper_id = _fetch_ss_id(paper)

    if not ss_paper_id:
        return {"citations": [], "source": "unavailable", "total": 0}

    url = f"{_SS_BASE}/paper/{ss_paper_id}/citations"
    params = {
        "fields": "title,authors,year,venue,externalIds,citationCount",
        "limit": min(limit, 50),
    }
    try:
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=15)
        if resp.status_code == 429:
            return {"citations": [], "source": "rate_limited", "total": 0}
        resp.raise_for_status()
        data = resp.json().get("data") or []
        citations = [_normalize_citation(r) for r in data if r.get("citingPaper")]
        # 按年份降序排列（最新施引在前）
        citations.sort(key=lambda x: x.get("year") or 0, reverse=True)
        return {
            "citations": citations,
            "source": "semantic_scholar",
            "total": len(citations),
        }
    except Exception:
        return {"citations": [], "source": "unavailable", "total": 0}
