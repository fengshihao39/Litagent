"""
Litagent - 本地 PDF 深度解析 API 路由

接口：
  POST /paper/analyze_pdf      上传 PDF 文件，执行完整深度解析
  POST /paper/analyze_ask      针对已解析论文提问
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from litagent.backend.app.services.analyze_service import (
    analyze_pdf_file,
    ask_question_on_paper,
)

router = APIRouter(prefix="/paper", tags=["analyze"])


# ─── 深度解析 ──────────────────────────────────────────────────────────────────


@router.post("/analyze_pdf")
async def api_analyze_pdf(
    file: UploadFile = File(..., description="上传的 PDF 文件"),
    force_reanalyze: bool = Form(
        default=False, description="是否强制重新解析（忽略缓存）"
    ),
) -> dict:
    """
    上传本地 PDF 文件，执行深度解析。

    流程：
      1. PDF 解析（PyMuPDF，支持中英文章节识别）
      2. Chunk 切分 + 语义检索
      3. 基础信息抽取（标题/作者/年份/摘要/关键词）
      4. 全文结构化解读（8 个维度，含证据片段引用）
      5. 答辩辅助输出（4 种格式）

    返回：
      {
        "paper_key":    str,
        "filename":     str,
        "basic_info":   dict,
        "structured":   str,
        "defense":      dict,
        "sections":     dict,
        "chunks":       list[dict],
        "retrieved":    list[dict],
        "page_count":   int,
        "char_count":   int,
        "total_chunks": int,
        "is_chinese":   bool,
        "source":       str,
      }
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件（.pdf 格式）")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="上传的文件为空")

    if len(pdf_bytes) > 100 * 1024 * 1024:  # 100MB 上限
        raise HTTPException(status_code=413, detail="文件过大，请上传 100MB 以内的 PDF")

    result = analyze_pdf_file(
        pdf_bytes=pdf_bytes,
        filename=file.filename,
        force_reanalyze=force_reanalyze,
    )

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    return result


# ─── 深度追问 ──────────────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    paper_key: str  # analyze_pdf 返回的 paper_key
    question: str  # 用户问题
    top_k: int = 5  # 检索证据片段数量


@router.post("/analyze_ask")
def api_analyze_ask(body: AskRequest) -> dict:
    """
    针对已深度解析的论文提问。

    返回：
      {
        "answer":   str,
        "evidence": list[dict],
      }
    """
    if not body.paper_key.strip():
        raise HTTPException(status_code=400, detail="paper_key 不能为空")
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    return ask_question_on_paper(
        question=body.question,
        paper_key=body.paper_key,
        top_k=body.top_k,
    )
