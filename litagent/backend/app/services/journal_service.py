"""
Litagent - 期刊信息补充服务

策略：
  1. 优先用 DOI 在 Crossref 查询，补充 publisher / ISSN / type / is_open_access / journal_name
  2. DOI 不可用时，尝试用标题在 Crossref 搜索
  3. 任何接口失败，静默返回空字段，不抛异常
"""

from __future__ import annotations

import requests

_CROSSREF_BASE = "https://api.crossref.org/works"
_EMAIL = "25209100302@stu.xidian.edu.cn"  # Polite Pool


def _crossref_headers() -> dict:
    return {
        "User-Agent": f"Litagent/1.0 (mailto:{_EMAIL})",
    }


def _extract_journal_info(item: dict) -> dict:
    """从 Crossref works 条目提取我们关心的字段。"""
    # publisher
    publisher = item.get("publisher") or ""

    # ISSN（可能有多个，取第一个）
    issn_list = item.get("ISSN") or []
    issn = issn_list[0] if issn_list else ""

    # type（article / journal-article / proceedings-article 等）
    doc_type = item.get("type") or ""

    # is_open_access（Crossref 本身不直接给 OA 标记，但 license 字段可以推断）
    licenses = item.get("license") or []
    is_open_access = any(
        "creativecommons" in (lic.get("URL") or "").lower() for lic in licenses
    )

    # journal_name（container-title 字段）
    container = item.get("container-title") or []
    journal_name = container[0] if container else ""

    # 短标题
    short_title_list = item.get("short-container-title") or []
    short_title = short_title_list[0] if short_title_list else ""

    # 发表年份（来自 published 或 issued）
    published = item.get("published") or item.get("issued") or {}
    date_parts = (published.get("date-parts") or [[]])[0]
    year = date_parts[0] if date_parts else None

    # subject / 学科领域
    subjects = item.get("subject") or []

    # 引用数（Crossref is-referenced-by-count）
    reference_count = item.get("is-referenced-by-count")

    return {
        "publisher": publisher,
        "issn": issn,
        "type": doc_type,
        "is_open_access": is_open_access,
        "journal_name": journal_name,
        "journal_short": short_title,
        "year": year,
        "subjects": subjects[:5],
        "reference_count_crossref": reference_count,
        "source": "crossref",
    }


def _fetch_by_doi(doi: str) -> dict | None:
    """用 DOI 精确查询 Crossref。"""
    url = f"{_CROSSREF_BASE}/{doi}"
    try:
        resp = requests.get(url, headers=_crossref_headers(), timeout=12)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        item = data.get("message") or {}
        return _extract_journal_info(item) if item else None
    except Exception:
        return None


def _fetch_by_title(title: str) -> dict | None:
    """用标题在 Crossref 模糊搜索，取相似度最高的第一条。"""
    params = {
        "query.title": title,
        "rows": 1,
        "select": (
            "DOI,title,publisher,ISSN,type,license,container-title,"
            "short-container-title,published,issued,subject,is-referenced-by-count"
        ),
        "mailto": _EMAIL,
    }
    try:
        resp = requests.get(
            _CROSSREF_BASE, params=params, headers=_crossref_headers(), timeout=12
        )
        resp.raise_for_status()
        items = (resp.json().get("message") or {}).get("items") or []
        if not items:
            return None
        return _extract_journal_info(items[0])
    except Exception:
        return None


def get_journal_info(paper: dict) -> dict:
    """
    获取期刊/出版信息。

    Args:
        paper: 包含 doi / title 等字段的论文字典

    Returns:
        {
          "publisher":        str,
          "issn":             str,
          "type":             str,
          "is_open_access":   bool,
          "journal_name":     str,
          "journal_short":    str,
          "year":             int | None,
          "subjects":         list[str],
          "reference_count_crossref": int | None,
          "source":           "crossref" | "unavailable",
        }
    """
    empty = {
        "publisher": "",
        "issn": "",
        "type": "",
        "is_open_access": False,
        "journal_name": "",
        "journal_short": "",
        "year": None,
        "subjects": [],
        "reference_count_crossref": None,
        "source": "unavailable",
    }

    doi = (paper.get("doi") or "").strip()
    title = (paper.get("title") or "").strip()

    # 优先 DOI 精确查询
    if doi:
        result = _fetch_by_doi(doi)
        if result:
            return result

    # 退化：标题模糊搜索（arXiv 等无 DOI 的论文）
    if title:
        result = _fetch_by_title(title)
        if result:
            return result

    return empty
