"""
Litagent - 前端网络层（论文详情 API）

对接后端 /paper/* 接口。
"""

from __future__ import annotations

import json
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
        st.toast(f"论文接口错误：{e}")
        return None


def fetch_paper_detail(paper: dict) -> dict:
    """
    从后端获取附加了热度分、收藏状态等扩展字段的论文详情。
    若后端不可达，直接返回原始 paper。
    """
    result = _post(
        "/paper/detail", {"paper_json": json.dumps(paper, ensure_ascii=False)}
    )
    return result if result else paper


def fetch_paper_summary(abstract: str) -> str:
    """获取摘要级结构化 AI 总结（兼容旧版，仅用摘要）。"""
    if not abstract.strip():
        return "暂无摘要，无法生成 AI 总结。"
    result = _post("/paper/summary", {"abstract": abstract})
    return (
        result.get("summary", "AI 总结生成失败，请稍后重试。")
        if result
        else "AI 总结生成失败，请稍后重试。"
    )


def fetch_full_summary(paper: dict) -> dict:
    """
    触发全文总结流程：下载 PDF → 解析 → DeepSeek 总结。
    返回：
      {
        "summary":       str,
        "source":        "pdf" | "abstract_fallback" | "error: ...",
        "page_count":    int,
        "pdf_available": bool,
      }
    超时设 120 秒（PDF 下载+解析+LLM 最长约 60s）。
    """
    result = _post(
        "/paper/fullsummary",
        {"paper_json": json.dumps(paper, ensure_ascii=False)},
        timeout=120,
    )
    if result:
        return result
    return {
        "summary": "AI 总结生成失败，请稍后重试。",
        "source": "error",
        "page_count": 0,
        "pdf_available": False,
    }


def fetch_title_zh(title: str) -> str:
    """获取中文标题翻译。"""
    if not title.strip():
        return ""
    result = _post("/paper/translate", {"title": title})
    return result.get("title_zh", "") if result else ""


def fetch_related_papers(
    target: dict, candidates: list[dict], top_k: int = 5
) -> list[dict]:
    """获取相似论文推荐。"""
    result = _post(
        "/paper/related",
        {
            "target_json": json.dumps(target, ensure_ascii=False),
            "candidates_json": json.dumps(candidates, ensure_ascii=False),
            "top_k": top_k,
        },
    )
    if result:
        return result.get("related", [])
    return []


def fetch_references(paper: dict) -> dict:
    """
    获取参考文献列表（真实数据库 + AI 推荐候选）。
    返回：
      {
        "references":     list[dict],
        "ai_suggestions": list[dict],
        "source":         str,
        "total":          int,
      }
    超时 30 秒（Semantic Scholar + DeepSeek 补充）。
    """
    result = _post(
        "/paper/references",
        {"paper_json": json.dumps(paper, ensure_ascii=False)},
        timeout=45,
    )
    if result:
        return result
    return {"references": [], "ai_suggestions": [], "source": "error", "total": 0}


def fetch_citations(paper: dict, limit: int = 20) -> dict:
    """
    获取施引文献列表。
    返回：
      {
        "citations": list[dict],
        "source":    str,
        "total":     int,
      }
    """
    result = _post(
        "/paper/citations",
        {"paper_json": json.dumps(paper, ensure_ascii=False), "limit": limit},
        timeout=30,
    )
    if result:
        return result
    return {"citations": [], "source": "error", "total": 0}


def fetch_journal_info(paper: dict) -> dict:
    """
    获取期刊出版信息（Crossref）。
    返回：
      {
        "publisher": str, "issn": str, "type": str,
        "is_open_access": bool, "journal_name": str, ...
      }
    """
    result = _post(
        "/paper/journal",
        {"paper_json": json.dumps(paper, ensure_ascii=False)},
        timeout=20,
    )
    if result:
        return result
    return {
        "publisher": "",
        "issn": "",
        "type": "",
        "is_open_access": False,
        "journal_name": "",
        "journal_short": "",
        "year": None,
        "subjects": [],
        "reference_count_crossref": None,
        "source": "error",
    }


def fetch_rag_summary(paper: dict, top_k: int = 8) -> dict:
    """
    触发 RAG 全流程总结：
      PDF 解析 → chunk → DeepSeek 语义检索 → 基于证据片段生成总结

    返回：
      {
        "summary":          str,
        "source":           "rag" | "rag_abstract" | "abstract_fallback",
        "retrieved_chunks": list[dict],   # 带 relevance_score 的证据片段
        "total_chunks":     int,
        "page_count":       int,
        "pdf_available":    bool,
      }
    超时 180 秒（chunk 打分 + 生成需要多次 LLM 调用）。
    """
    result = _post(
        "/paper/rag_summary",
        {
            "paper_json": json.dumps(paper, ensure_ascii=False),
            "top_k": top_k,
        },
        timeout=180,
    )
    if result:
        return result
    return {
        "summary": "RAG 总结生成失败，请稍后重试。",
        "source": "error",
        "retrieved_chunks": [],
        "total_chunks": 0,
        "page_count": 0,
        "pdf_available": False,
    }
