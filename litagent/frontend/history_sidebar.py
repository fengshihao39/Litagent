"""
Litagent - 历史记录侧边栏组件

渲染左侧历史会话列表 + 新对话按钮。
"""

from __future__ import annotations

import streamlit as st

from litagent.frontend.history_api import (
    create_session,
    delete_session,
    list_sessions,
)
from litagent.frontend.session_state import new_conversation


def render_history_sidebar() -> None:
    """在 st.sidebar 内渲染历史对话区域。"""
    with st.sidebar:
        # 新对话按钮
        if st.button("＋ 新对话", use_container_width=True, type="primary"):
            sid = create_session("新对话")
            if sid:
                st.session_state["current_session_id"] = sid
            new_conversation()
            st.rerun()

        st.divider()
        st.caption("历史搜索记录")

        sessions = list_sessions(limit=30)
        if not sessions:
            st.caption("暂无历史记录")
            return

        for sess in sessions:
            _render_session_item(sess)


def _render_session_item(sess: dict) -> None:
    """渲染单条历史会话条目。"""
    is_current = st.session_state.get("current_session_id") == sess["id"]

    label = sess.get("title") or sess.get("last_query") or "新对话"
    if len(label) > 24:
        label = label[:22] + "…"

    # 会话按钮（点击后恢复该会话的搜索结果）
    col_btn, col_del = st.columns([5, 1])
    with col_btn:
        btn_type = "primary" if is_current else "secondary"
        if st.button(
            label,
            key=f"sess_{sess['id']}",
            use_container_width=True,
            type=btn_type,
        ):
            _restore_session(sess["id"])
            st.rerun()

    with col_del:
        if st.button("✕", key=f"del_{sess['id']}", help="删除此会话"):
            delete_session(sess["id"])
            if st.session_state.get("current_session_id") == sess["id"]:
                new_conversation()
            st.rerun()


def _restore_session(session_id: str) -> None:
    """恢复历史会话：加载该会话最后一次搜索记录到 session_state。"""
    import json

    from litagent.frontend.history_api import get_session_detail

    detail = get_session_detail(session_id)
    if not detail:
        return

    records = detail.get("records", [])
    if not records:
        st.session_state["search_results"] = []
        st.session_state["last_query"] = ""
    else:
        last = records[-1]
        try:
            results = json.loads(last.get("results_json", "[]"))
        except (ValueError, TypeError):
            results = []
        st.session_state["search_results"] = results
        st.session_state["last_query"] = last.get("query", "")
        st.session_state["search_submitted"] = True

    st.session_state["current_session_id"] = session_id
    st.session_state["page"] = "search"
    st.session_state["current_paper"] = None
