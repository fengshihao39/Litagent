"""
Litagent - 前端网络层（本地 PDF 深度解析 API）

对接后端 /paper/analyze_pdf 和 /paper/analyze_ask 接口。
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE = os.getenv("LITAGENT_FRONTEND_API_URL", "http://localhost:8000")


def _post(path: str, body: dict, timeout: int = 30) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}{path}", json=body, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.toast(f"解析接口错误：{e}")
        return None


def upload_and_analyze_pdf(
    pdf_bytes: bytes,
    filename: str,
    force_reanalyze: bool = False,
) -> dict | None:
    """
    上传 PDF 文件到后端，执行深度解析。

    返回结构：
      {
        "paper_key":    str,
        "filename":     str,
        "basic_info":   dict,    # 标题/作者/年份/摘要/关键词/页数
        "structured":   str,     # 8维结构化解读文本
        "defense":      dict,    # 答辩辅助（4种格式）
        "sections":     dict,    # 6个章节原文
        "chunks":       list,    # 所有 chunk
        "retrieved":    list,    # 检索到的证据片段
        "page_count":   int,
        "char_count":   int,
        "total_chunks": int,
        "is_chinese":   bool,
        "source":       str,
      }

    超时设置 300 秒（大文件解析+多次 LLM 调用最多约 2 分钟）。
    """
    try:
        r = requests.post(
            f"{API_BASE}/paper/analyze_pdf",
            files={"file": (filename, pdf_bytes, "application/pdf")},
            data={"force_reanalyze": str(force_reanalyze).lower()},
            timeout=300,
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        st.toast("解析超时，请稍后重试（大文件可能需要 3-5 分钟）")
        return None
    except requests.RequestException as e:
        st.toast(f"PDF 解析失败：{e}")
        return None


def ask_on_paper(
    paper_key: str,
    question: str,
    top_k: int = 5,
) -> dict:
    """
    针对已解析论文提问。

    返回：
      {
        "answer":   str,
        "evidence": list[dict],
      }
    """
    result = _post(
        "/paper/analyze_ask",
        {
            "paper_key": paper_key,
            "question": question,
            "top_k": top_k,
        },
        timeout=60,
    )
    if result:
        return result
    return {"answer": "AI 回答生成失败，请稍后重试。", "evidence": []}
