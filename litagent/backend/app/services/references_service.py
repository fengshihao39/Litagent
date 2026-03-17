"""
Litagent - 参考文献服务

策略：
  1. 优先从 Semantic Scholar Graph API 拉取真实参考文献列表
  2. 若真实结果 < 3 条，用 DeepSeek 补充最多 2 条候选（单独标注 ai_suggested=True）
  3. AI 建议条目再经 Semantic Scholar / Crossref 复核，拿到真实数据后替换
  4. 限流 / 网络异常时自动降级，绝不造假
"""

from __future__ import annotations

import time
import re
import requests
from openai import OpenAI

from litagent.backend.app.core.config import get_deepseek_api_key

_SS_BASE = "https://api.semanticscholar.org/graph/v1"
_CROSSREF_BASE = "https://api.crossref.org/works"
_EMAIL = "25209100302@stu.xidian.edu.cn"  # Polite Pool

_client = OpenAI(
    api_key=get_deepseek_api_key(),
    base_url="https://api.deepseek.com",
)

# ── 工具函数 ──────────────────────────────────────────────────────────────────


def _ss_headers() -> dict:
    return {"User-Agent": f"Litagent/1.0 (mailto:{_EMAIL})"}


def _normalize_ref(raw: dict, ai_suggested: bool = False) -> dict:
    """把 Semantic Scholar 的 reference 字段统一成我们的格式。"""
    cited = raw.get("citedPaper") or {}
    ext_ids = cited.get("externalIds") or {}
    return {
        "title": cited.get("title") or raw.get("title") or "",
        "authors": [a.get("name", "") for a in (cited.get("authors") or [])],
        "year": cited.get("year") or raw.get("year"),
        "venue": cited.get("venue") or "",
        "doi": ext_ids.get("DOI") or "",
        "arxiv_id": ext_ids.get("ArXiv") or "",
        "ss_paper_id": cited.get("paperId") or "",
        "citation_count": cited.get("citationCount"),
        "abs_url": (
            f"https://arxiv.org/abs/{ext_ids['ArXiv']}"
            if ext_ids.get("ArXiv")
            else (f"https://doi.org/{ext_ids['DOI']}" if ext_ids.get("DOI") else "")
        ),
        "ai_suggested": ai_suggested,
    }


# ── Semantic Scholar 查询 ─────────────────────────────────────────────────────


def _fetch_ss_references_by_id(ss_paper_id: str) -> list[dict] | None:
    """用 Semantic Scholar paper ID 拉取参考文献，返回原始列表或 None（失败时）。"""
    url = f"{_SS_BASE}/paper/{ss_paper_id}/references"
    params = {
        "fields": "title,authors,year,venue,externalIds,citationCount",
        "limit": 50,
    }
    try:
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=15)
        if resp.status_code == 429:
            return None  # 限流，降级
        resp.raise_for_status()
        data = resp.json()
        return data.get("data") or []
    except Exception:
        return None


def _fetch_ss_id_by_doi(doi: str) -> str | None:
    """通过 DOI 在 Semantic Scholar 查 paper ID。"""
    url = f"{_SS_BASE}/paper/DOI:{doi}"
    params = {"fields": "paperId"}
    try:
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=10)
        if resp.status_code in (404, 429):
            return None
        resp.raise_for_status()
        return resp.json().get("paperId")
    except Exception:
        return None


def _fetch_ss_id_by_arxiv(arxiv_id: str) -> str | None:
    """通过 arXiv ID 在 Semantic Scholar 查 paper ID。"""
    url = f"{_SS_BASE}/paper/arXiv:{arxiv_id}"
    params = {"fields": "paperId"}
    try:
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=10)
        if resp.status_code in (404, 429):
            return None
        resp.raise_for_status()
        return resp.json().get("paperId")
    except Exception:
        return None


def _fetch_ss_id_by_title(title: str) -> str | None:
    """通过标题搜索 Semantic Scholar，取第一条结果的 paper ID。"""
    url = f"{_SS_BASE}/paper/search"
    params = {"query": title, "fields": "paperId", "limit": 1}
    try:
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=10)
        if resp.status_code == 429:
            return None
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return data[0]["paperId"] if data else None
    except Exception:
        return None


# ── DeepSeek 补充建议 ─────────────────────────────────────────────────────────

_SUGGEST_REFS_PROMPT = """\
你是一名学术助手。用户会给你一篇论文的标题和摘要。
请根据该论文的研究方向，推断 2 条最有可能被该论文引用的经典参考文献。

输出格式（严格遵守，每条一行，用 || 分隔字段）：
标题 || 第一作者姓 || 发表年份 || 期刊/会议名称

规则：
- 只输出 2 行，不加编号、不加解释、不加多余内容
- 年份必须是 4 位数字
- 如果不确定，只输出你最有把握的条目
"""


def _deepseek_suggest_refs(title: str, abstract: str) -> list[dict]:
    """让 DeepSeek 根据标题+摘要推断 2 条可能的参考文献。"""
    if not title.strip():
        return []
    user_msg = (
        f"标题：{title}\n\n摘要：{abstract[:800]}" if abstract else f"标题：{title}"
    )
    try:
        resp = _client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _SUGGEST_REFS_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=200,
            temperature=0.2,
        )
        content = (resp.choices[0].message.content or "").strip()
        results = []
        for line in content.splitlines():
            parts = [p.strip() for p in line.split("||")]
            if len(parts) >= 2:
                ref_title = parts[0]
                first_author = parts[1] if len(parts) > 1 else ""
                year_str = parts[2] if len(parts) > 2 else ""
                venue = parts[3] if len(parts) > 3 else ""
                # 年份校验
                year = None
                if re.fullmatch(r"\d{4}", year_str):
                    year = int(year_str)
                if ref_title:
                    results.append(
                        {
                            "title": ref_title,
                            "authors": [first_author] if first_author else [],
                            "year": year,
                            "venue": venue,
                            "doi": "",
                            "arxiv_id": "",
                            "ss_paper_id": "",
                            "citation_count": None,
                            "abs_url": "",
                            "ai_suggested": True,
                        }
                    )
        return results[:2]
    except Exception:
        return []


# ── AI 候选复核（用 Semantic Scholar 查真实数据替换） ────────────────────────


def _verify_ai_ref(ref: dict) -> dict:
    """
    尝试用标题在 Semantic Scholar 查真实数据。
    若找到，用真实数据替换 AI 候选的字段，但保留 ai_suggested=True 标记。
    """
    title = ref.get("title", "")
    if not title:
        return ref
    try:
        url = f"{_SS_BASE}/paper/search"
        params = {
            "query": title,
            "fields": "title,authors,year,venue,externalIds,citationCount",
            "limit": 1,
        }
        resp = requests.get(url, params=params, headers=_ss_headers(), timeout=10)
        if resp.status_code != 200:
            return ref
        data = resp.json().get("data") or []
        if not data:
            return ref
        hit = data[0]
        ext = hit.get("externalIds") or {}
        doi = ext.get("DOI") or ""
        arxiv_id = ext.get("ArXiv") or ""
        verified = {
            "title": hit.get("title") or title,
            "authors": [a.get("name", "") for a in (hit.get("authors") or [])],
            "year": hit.get("year") or ref.get("year"),
            "venue": hit.get("venue") or ref.get("venue") or "",
            "doi": doi,
            "arxiv_id": arxiv_id,
            "ss_paper_id": hit.get("paperId") or "",
            "citation_count": hit.get("citationCount"),
            "abs_url": (
                f"https://arxiv.org/abs/{arxiv_id}"
                if arxiv_id
                else (f"https://doi.org/{doi}" if doi else "")
            ),
            "ai_suggested": True,  # 保留标记：来源为 AI 推荐，但已核验
            "ai_verified": True,
        }
        return verified
    except Exception:
        return ref


# ── 主入口 ────────────────────────────────────────────────────────────────────


def get_references(paper: dict) -> dict:
    """
    获取论文参考文献列表。

    Args:
        paper: 包含 doi / arxiv_id / ss_paper_id / title / abstract 等字段的论文字典

    Returns:
        {
          "references": list[dict],   # 真实参考文献
          "ai_suggestions": list[dict], # AI 推荐（独立展示）
          "source": str,             # "semantic_scholar" | "unavailable"
          "total": int,
        }
    """
    doi = (paper.get("doi") or "").strip()
    arxiv_id = (paper.get("arxiv_id") or "").strip()
    ss_paper_id = (paper.get("ss_paper_id") or "").strip()
    title = (paper.get("title") or "").strip()
    abstract = paper.get("summary") or paper.get("abstract") or ""

    # 1. 找到 Semantic Scholar paper ID
    if not ss_paper_id:
        if doi:
            ss_paper_id = _fetch_ss_id_by_doi(doi) or ""
            time.sleep(0.5)
        if not ss_paper_id and arxiv_id:
            ss_paper_id = _fetch_ss_id_by_arxiv(arxiv_id) or ""
            time.sleep(0.5)
        if not ss_paper_id and title:
            ss_paper_id = _fetch_ss_id_by_title(title) or ""
            time.sleep(0.5)

    # 2. 拉取真实参考文献
    real_refs: list[dict] = []
    source = "unavailable"
    if ss_paper_id:
        raw_list = _fetch_ss_references_by_id(ss_paper_id)
        if raw_list is not None:
            real_refs = [_normalize_ref(r) for r in raw_list if r.get("citedPaper")]
            source = "semantic_scholar"

    # 3. 若真实结果 < 3，DeepSeek 补充最多 2 条
    ai_suggestions: list[dict] = []
    if len(real_refs) < 3 and title:
        raw_ai = _deepseek_suggest_refs(title, abstract)
        # 对每条 AI 候选做复核
        for ai_ref in raw_ai:
            time.sleep(0.3)
            verified = _verify_ai_ref(ai_ref)
            ai_suggestions.append(verified)

    return {
        "references": real_refs,
        "ai_suggestions": ai_suggestions,
        "source": source,
        "total": len(real_refs),
    }
