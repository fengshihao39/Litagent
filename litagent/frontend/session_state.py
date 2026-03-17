"""
Litagent - 前端全局 session_state 管理

集中管理所有 Streamlit session_state 的初始化，
避免各模块重复写 if key not in st.session_state。
"""

from __future__ import annotations

import streamlit as st


def init_session_state() -> None:
    """初始化所有全局 session_state 键，只在缺失时设置默认值。"""
    defaults: dict = {
        # 页面路由："search" | "detail"
        "page": "search",
        # 当前查看的论文（dict）
        "current_paper": None,
        # 当前会话的所有搜索结果（list[dict]）
        "search_results": [],
        # 当前 session id（str | None）
        "current_session_id": None,
        # 是否已触发搜索
        "search_submitted": False,
        # 最近一次搜索词
        "last_query": "",
        # AI 总结缓存 {paper_key: summary_text}
        "summary_cache": {},
        # 中文标题缓存 {title: title_zh}
        "title_zh_cache": {},
        # 收藏状态缓存 {paper_key: bool}
        "favorite_cache": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def go_to_search() -> None:
    """切换到搜索页。"""
    st.session_state["page"] = "search"
    st.session_state["current_paper"] = None


def go_to_detail(paper: dict) -> None:
    """切换到论文详情页。"""
    st.session_state["page"] = "detail"
    st.session_state["current_paper"] = paper


def set_search_results(results: list[dict], query: str) -> None:
    """更新搜索结果和当前 query。"""
    st.session_state["search_results"] = results
    st.session_state["last_query"] = query
    st.session_state["search_submitted"] = True


def new_conversation() -> None:
    """开启新对话，清空本次搜索状态（不影响历史记录）。"""
    st.session_state["search_results"] = []
    st.session_state["search_submitted"] = False
    st.session_state["last_query"] = ""
    st.session_state["current_session_id"] = None
    st.session_state["page"] = "search"
    st.session_state["current_paper"] = None
