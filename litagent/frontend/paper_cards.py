"""
Litagent - 搜索结果卡片组件

把原来的 expander 列表替换为可点击的论文卡片，
点击"查看详情"后切换到详情页。
"""

from __future__ import annotations

import streamlit as st

from litagent.frontend.session_state import go_to_detail


def render_paper_cards(results: list[dict]) -> None:
    """渲染论文卡片列表。"""
    if not results:
        st.warning("未找到相关文献，请调整关键词重试。")
        return

    st.success(f"共找到 {len(results)} 篇相关文献")

    for idx, paper in enumerate(results):
        _render_single_card(paper, idx)


def _render_single_card(paper: dict, idx: int) -> None:
    """渲染单张论文卡片。"""
    title = paper.get("title") or "未命名"
    year = paper.get("year") or ""
    authors = paper.get("authors") or []
    venue = paper.get("venue") or ""
    citation_count = paper.get("citation_count") or 0
    abstract = paper.get("abstract") or ""
    source = paper.get("source") or ""
    tldr = paper.get("tldr") or ""
    abs_url = paper.get("abs_url") or ""

    author_str = "，".join(authors[:3])
    if len(authors) > 3:
        author_str += f" 等 {len(authors)} 人"

    with st.container(border=True):
        # 标题行
        title_col, meta_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"**{title}**")
        with meta_col:
            if year:
                st.caption(f"📅 {year}")

        # 作者 / 来源行
        info_parts = []
        if author_str:
            info_parts.append(f"👤 {author_str}")
        if venue:
            info_parts.append(f"📖 {venue}")
        if source:
            src_label = {
                "arxiv": "arXiv",
                "semantic_scholar": "S2",
                "crossref": "Crossref",
                "ieee": "IEEE",
            }.get(source, source.upper())
            info_parts.append(f"🔗 {src_label}")
        if info_parts:
            st.caption("  ·  ".join(info_parts))

        # TLDR 或摘要片段
        if tldr:
            st.caption(f"💡 {tldr}")
        elif abstract:
            preview = abstract[:180] + "…" if len(abstract) > 180 else abstract
            st.caption(preview)

        # 底部操作栏
        btn_col, cite_col, link_col = st.columns([2, 2, 2])
        with btn_col:
            if st.button(
                "查看详情 →",
                key=f"detail_{idx}",
                use_container_width=True,
                type="primary",
            ):
                go_to_detail(paper)
                st.rerun()
        with cite_col:
            if citation_count:
                st.caption(f"📊 被引 {citation_count} 次")
        with link_col:
            if abs_url:
                st.markdown(f"[原文链接]({abs_url})")
