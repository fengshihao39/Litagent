"""
Litagent - 前端网络层（历史记录 API）

对接后端 /history/* 接口，供前端各模块调用。
"""

from __future__ import annotations

import json
import os

import requests
import streamlit as st

API_BASE = os.getenv("LITAGENT_FRONTEND_API_URL", "http://localhost:8000")


def _post(path: str, body: dict) -> dict | None:
    try:
        r = requests.post(f"{API_BASE}{path}", json=body, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.toast(f"历史记录接口错误：{e}")
        return None


def _get(path: str, params: dict | None = None) -> dict | list | None:
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        st.toast(f"历史记录接口错误：{e}")
        return None


def _delete(path: str) -> bool:
    try:
        r = requests.delete(f"{API_BASE}{path}", timeout=10)
        r.raise_for_status()
        return True
    except requests.RequestException:
        return False


# ─── 会话 ────────────────────────────────────────────────────────────────────


def create_session(title: str = "新对话") -> str | None:
    """新建会话，返回 session_id。"""
    result = _post("/history/sessions", {"title": title})
    return result["id"] if result else None


def list_sessions(limit: int = 50) -> list[dict]:
    """获取历史会话列表。"""
    result = _get("/history/sessions", {"limit": limit})
    return result if isinstance(result, list) else []


def get_session_detail(session_id: str) -> dict | None:
    """获取会话详情（含搜索记录）。"""
    result = _get(f"/history/sessions/{session_id}")  # type: ignore[assignment]
    return result if isinstance(result, dict) else None


def delete_session(session_id: str) -> bool:
    """删除会话。"""
    return _delete(f"/history/sessions/{session_id}")


def rename_session(session_id: str, new_title: str) -> bool:
    """重命名会话。"""
    try:
        r = requests.patch(
            f"{API_BASE}/history/sessions/{session_id}/title",
            json={"title": new_title},
            timeout=10,
        )
        r.raise_for_status()
        return True
    except requests.RequestException:
        return False


# ─── 搜索记录 ────────────────────────────────────────────────────────────────


def save_search_record(session_id: str, query: str, results: list[dict]) -> str | None:
    """保存搜索记录，返回 record_id。"""
    result = _post(
        "/history/search-records",
        {
            "session_id": session_id,
            "query": query,
            "results_json": json.dumps(results, ensure_ascii=False),
        },
    )
    return result.get("record_id") if result else None


# ─── 收藏 ────────────────────────────────────────────────────────────────────


def toggle_favorite(paper_key: str, paper_json: str) -> str | None:
    """收藏/取消收藏，返回 'added' 或 'removed'。"""
    result = _post(
        "/history/favorites/toggle",
        {"paper_key": paper_key, "paper_json": paper_json},
    )
    return result.get("action") if result else None


def list_favorites() -> list[dict]:
    """获取收藏列表。"""
    result = _get("/history/favorites")
    return result if isinstance(result, list) else []


def check_favorite(paper_key: str) -> bool:
    """检查是否已收藏。"""
    result = _get(f"/history/favorites/check/{paper_key}")
    if isinstance(result, dict):
        return bool(result.get("is_favorite"))
    return False
