"""
Litagent - 论文详情 & 相关功能 API 路由
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from litagent.backend.app.services.paper_detail_service import build_paper_detail
from litagent.backend.app.services.paper_summary_service import (
    generate_paper_summary,
    translate_title_to_chinese,
)
from litagent.backend.app.services.pdf_downloader import download_pdf, resolve_pdf_url
from litagent.backend.app.services.pdf_parser import (
    make_fallback_from_abstract,
    parse_pdf,
)
from litagent.backend.app.services.recommend_service import find_related_papers
from litagent.backend.app.services.references_service import get_references
from litagent.backend.app.services.citations_service import get_citations
from litagent.backend.app.services.journal_service import get_journal_info
from litagent.backend.app.services.rag_service import run_rag_summary

router = APIRouter(prefix="/paper", tags=["paper"])


class PaperDetailRequest(BaseModel):
    paper_json: str  # 序列化后的 PaperResult JSON 字符串


class SummaryRequest(BaseModel):
    abstract: str


class FullSummaryRequest(BaseModel):
    paper_json: str  # 完整论文字典（含 pdf_url / arxiv_id 等）


class TranslateRequest(BaseModel):
    title: str


class RelatedRequest(BaseModel):
    target_json: str  # 目标论文 JSON 字符串
    candidates_json: str  # 候选池 JSON 字符串（即当次搜索结果列表）
    top_k: int = 5


# ─── 详情 ─────────────────────────────────────────────────────────────────────


@router.post("/detail")
def api_paper_detail(body: PaperDetailRequest) -> dict:
    """
    传入一篇论文的 JSON，返回附加了热度分、收藏状态等扩展字段的详情对象。
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e
    return build_paper_detail(paper)


# ─── AI 总结（旧接口，摘要兜底，保持兼容） ───────────────────────────────────


@router.post("/summary")
def api_paper_summary(body: SummaryRequest) -> dict:
    """
    根据摘要生成结构化 AI 总结（摘要级，兼容旧版前端）。
    """
    if not body.abstract.strip():
        raise HTTPException(status_code=400, detail="摘要不能为空")
    summary = generate_paper_summary(abstract=body.abstract)
    return {"summary": summary, "source": "abstract_fallback"}


# ─── AI 全文总结（新接口：下载 PDF → 解析 → 总结） ───────────────────────────


@router.post("/fullsummary")
def api_paper_fullsummary(body: FullSummaryRequest) -> dict:
    """
    完整全文总结流程：
      1. 解析 paper_json 拿到 pdf_url / arxiv_id
      2. 尝试下载 PDF 到本地缓存
      3. 用 PyMuPDF 解析全文
      4. 调用 DeepSeek 生成基于全文的结构化总结
      5. 若 PDF 不可用，自动降级为摘要总结

    返回：
      {
        "summary": str,
        "source": "pdf" | "abstract_fallback" | "error: ...",
        "page_count": int,
        "pdf_available": bool
      }
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e

    title = paper.get("title", "")
    abstract = paper.get("summary") or paper.get("abstract") or ""
    tldr = paper.get("tldr", "")
    venue = paper.get("venue", "")
    year = str(paper.get("year") or "")
    keywords = paper.get("keywords") or paper.get("categories") or []

    # paper_key 用于缓存命名
    from litagent.backend.app.services.paper_detail_service import _make_paper_key

    paper_key = _make_paper_key(paper)

    # 1. 尝试找 pdf_url
    pdf_url = resolve_pdf_url(paper)

    # 2. 下载 PDF
    pdf_path = None
    if pdf_url:
        pdf_path = download_pdf(pdf_url, paper_key)

    # 3. 解析 PDF
    if pdf_path:
        parsed = parse_pdf(pdf_path, paper_key)
    else:
        # 降级：用摘要+tldr 构造兜底
        parsed = make_fallback_from_abstract(abstract, tldr)

    pdf_text = parsed.get("full_text", "")
    parse_source = parsed.get("source", "abstract_fallback")
    page_count = parsed.get("page_count", 0)

    # 4. 生成 AI 总结
    summary = generate_paper_summary(
        abstract=abstract,
        pdf_text=pdf_text,
        title=title,
        venue=venue,
        year=year,
        keywords=keywords if isinstance(keywords, list) else [],
    )

    return {
        "summary": summary,
        "source": parse_source,
        "page_count": page_count,
        "pdf_available": pdf_path is not None,
    }


# ─── 标题翻译 ─────────────────────────────────────────────────────────────────


@router.post("/translate")
def api_translate_title(body: TranslateRequest) -> dict:
    """将英文标题翻译为中文。"""
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    title_zh = translate_title_to_chinese(body.title)
    return {"title_zh": title_zh}


# ─── 相关论文 ─────────────────────────────────────────────────────────────────


@router.post("/related")
def api_related_papers(body: RelatedRequest) -> dict:
    """
    从候选池中推荐与目标论文最相似的论文。
    candidates_json 就是当次搜索返回的结果列表 JSON。
    """
    try:
        target = json.loads(body.target_json)
        candidates = json.loads(body.candidates_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}") from e

    if not isinstance(candidates, list):
        raise HTTPException(status_code=400, detail="candidates_json 必须是数组")

    related = find_related_papers(target, candidates, top_k=body.top_k)
    return {"related": related}


# ─── 参考文献 ──────────────────────────────────────────────────────────────────


class ReferencesRequest(BaseModel):
    paper_json: str  # 序列化后的论文 JSON


@router.post("/references")
def api_paper_references(body: ReferencesRequest) -> dict:
    """
    获取论文参考文献列表。
    优先 Semantic Scholar 真实数据；不足 3 条时由 DeepSeek 补充最多 2 条（单独标注）。

    返回：
      {
        "references":    list[dict],
        "ai_suggestions": list[dict],
        "source":        str,
        "total":         int,
      }
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e
    return get_references(paper)


# ─── 施引文献 ──────────────────────────────────────────────────────────────────


class CitationsRequest(BaseModel):
    paper_json: str
    limit: int = 20


@router.post("/citations")
def api_paper_citations(body: CitationsRequest) -> dict:
    """
    获取施引该论文的文献列表（来源：Semantic Scholar）。

    返回：
      {
        "citations": list[dict],
        "source":    str,
        "total":     int,
      }
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e
    return get_citations(paper, limit=body.limit)


# ─── 期刊信息 ──────────────────────────────────────────────────────────────────


class JournalRequest(BaseModel):
    paper_json: str


@router.post("/journal")
def api_paper_journal(body: JournalRequest) -> dict:
    """
    补充期刊出版信息（来源：Crossref）。

    返回：
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
        "source":           str,
      }
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e
    return get_journal_info(paper)


# ─── RAG 总结（第三阶段核心接口） ──────────────────────────────────────────────


class RagSummaryRequest(BaseModel):
    paper_json: str  # 完整论文字典（含 pdf_url / arxiv_id 等）
    top_k: int = 8  # 检索返回的证据片段数量


@router.post("/rag_summary")
def api_paper_rag_summary(body: RagSummaryRequest) -> dict:
    """
    RAG 全流程总结接口：
      1. 下载 PDF → PyMuPDF 解析 → chunk 切分
      2. DeepSeek 对所有 chunk 做语义相关度打分
      3. 取 top-k 证据片段
      4. 基于证据片段生成带引用标注的结构化总结
      5. 若 PDF 不可用，自动降级为摘要兜底

    返回：
      {
        "summary":          str,          # 结构化总结（含证据片段编号引用）
        "source":           str,          # "rag" | "rag_abstract" | "abstract_fallback"
        "retrieved_chunks": list[dict],   # 证据片段列表（含 relevance_score）
        "total_chunks":     int,          # 全文切分总 chunk 数
        "page_count":       int,
        "pdf_available":    bool,
      }
    """
    try:
        paper = json.loads(body.paper_json)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"paper_json 解析失败: {e}") from e
    return run_rag_summary(paper, top_k=body.top_k)
