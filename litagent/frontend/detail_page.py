"""
Litagent - 论文详情页组件

仿 Bohrium 风格的双栏详情页：
  左侧：元信息（被引、热度、收藏、来源、作者、关键词、相似论文）
  右侧：英文标题、中文标题、摘要、AI 总结、参考文献占位
"""

from __future__ import annotations

import json

import streamlit as st

from litagent.frontend.history_api import toggle_favorite
from litagent.frontend.paper_api import (
    fetch_citations,
    fetch_full_summary,
    fetch_journal_info,
    fetch_paper_detail,
    fetch_rag_summary,
    fetch_references,
    fetch_related_papers,
    fetch_title_zh,
)
from litagent.frontend.session_state import go_to_detail, go_to_search


def render_detail_page(paper: dict, all_results: list[dict]) -> None:
    """渲染论文详情页完整布局。"""

    # 进入详情页时强制滚回顶部
    st.components.v1.html(
        "<script>window.parent.document.querySelector('.main').scrollTo(0, 0);</script>",
        height=0,
    )

    # 获取后端扩展字段（热度分、收藏状态、paper_key）
    with st.spinner("加载论文详情…"):
        detail = fetch_paper_detail(paper)

    # 返回按钮
    if st.button("← 返回搜索结果", type="secondary"):
        go_to_search()
        st.rerun()

    st.divider()

    left_col, right_col = st.columns([1, 2], gap="large")

    with left_col:
        _render_left_panel(detail, all_results)

    with right_col:
        _render_right_panel(detail)


# ─── 左侧面板 ─────────────────────────────────────────────────────────────────


def _render_left_panel(detail: dict, all_results: list[dict]) -> None:
    """左侧：指标卡片 + 元信息 + 相似论文。"""

    citation_count = detail.get("citation_count") or 0
    heat_score = detail.get("heat_score") or 0.0
    heat_label = detail.get("heat_label") or "未知"
    is_fav = detail.get("is_favorite") or st.session_state.get(
        "favorite_cache", {}
    ).get(detail.get("paper_key", ""), False)
    paper_key = detail.get("paper_key") or ""

    # ── 指标行 ──
    m1, m2 = st.columns(2)
    m1.metric("被引次数", citation_count)
    m2.metric("热度", f"{heat_label}  ({heat_score:.2f})")

    # ── 收藏按钮 ──
    fav_label = "★ 已收藏" if is_fav else "☆ 收藏"
    if st.button(fav_label, key="fav_btn", use_container_width=True):
        action = toggle_favorite(
            paper_key=paper_key,
            paper_json=json.dumps(detail, ensure_ascii=False),
        )
        if action:
            new_state = action == "added"
            if "favorite_cache" not in st.session_state:
                st.session_state["favorite_cache"] = {}
            st.session_state["favorite_cache"][paper_key] = new_state
            msg = "已收藏" if new_state else "已取消收藏"
            st.toast(msg)
            st.rerun()

    st.divider()

    # ── 元信息 ──
    venue = detail.get("venue") or ""
    doi = detail.get("doi") or ""
    year = detail.get("year") or ""
    source = detail.get("source") or ""
    abs_url = detail.get("abs_url") or ""
    authors = detail.get("authors") or []
    keywords = detail.get("keywords") or []

    if venue:
        st.markdown(f"**期刊/来源**\n\n{venue}")
    if doi:
        st.markdown(f"**DOI**\n\n`{doi}`")
    if year:
        st.markdown(f"**年份**\n\n{year}")
    if source:
        src_label = {
            "arxiv": "arXiv",
            "semantic_scholar": "Semantic Scholar",
            "crossref": "Crossref",
            "ieee": "IEEE Xplore",
        }.get(source, source.upper())
        st.markdown(f"**数据来源**\n\n{src_label}")
    if abs_url:
        st.markdown(f"**[查看原文]({abs_url})**")

    if authors:
        st.divider()
        st.markdown("**作者**")
        for a in authors[:6]:
            st.caption(a)
        if len(authors) > 6:
            st.caption(f"… 共 {len(authors)} 位作者")

    if keywords:
        st.divider()
        st.markdown("**关键词**")
        st.write("  ".join(f"`{k}`" for k in keywords[:8]))

    # ── 相似论文 ──
    st.divider()
    _render_related_papers(detail, all_results)


def _render_related_papers(paper: dict, all_results: list[dict]) -> None:
    """左侧下方：相似论文推荐。"""
    st.markdown("**相关论文**")

    if not all_results:
        st.caption("暂无候选池，请先执行搜索")
        return

    with st.spinner("推荐相似论文…"):
        related = fetch_related_papers(paper, all_results, top_k=5)

    if not related:
        st.caption("未找到足够相似的论文")
        return

    for i, rel in enumerate(related):
        rel_title = rel.get("title") or "未命名"
        rel_year = rel.get("year") or ""
        rel_sim = rel.get("similarity_score") or 0.0
        rel_venue = rel.get("venue") or ""
        rel_authors = rel.get("authors") or []

        with st.container(border=True):
            short_title = rel_title[:60] + "…" if len(rel_title) > 60 else rel_title
            st.caption(f"**{short_title}**")
            meta = []
            if rel_year:
                meta.append(str(rel_year))
            if rel_venue:
                meta.append(rel_venue[:20])
            if rel_authors:
                meta.append(rel_authors[0])
            st.caption("  ·  ".join(meta))
            st.caption(f"相似度 {rel_sim:.0%}")

            if st.button("查看", key=f"rel_{i}", use_container_width=True):
                go_to_detail(rel)
                st.rerun()


# ─── 右侧面板 ─────────────────────────────────────────────────────────────────


def _render_right_panel(detail: dict) -> None:
    """右侧：标题、摘要、AI 总结。"""
    title_en = detail.get("title") or "未命名"
    # arXiv/Semantic Scholar 用 summary，Crossref/IEEE 用 abstract
    abstract = detail.get("summary") or detail.get("abstract") or ""
    paper_key = detail.get("paper_key") or title_en[:60]

    # ── 英文标题 ──
    st.markdown(f"## {title_en}")

    # ── 中文标题（懒加载缓存）──
    cache: dict = st.session_state.get("title_zh_cache", {})
    if title_en not in cache:
        with st.spinner("翻译标题中…"):
            title_zh = fetch_title_zh(title_en)
        cache[title_en] = title_zh
        st.session_state["title_zh_cache"] = cache
    else:
        title_zh = cache[title_en]

    if title_zh:
        st.markdown(f"*{title_zh}*")

    st.divider()

    # ── 摘要 ──
    st.markdown("### 摘要")
    if abstract:
        st.write(abstract)
    else:
        st.caption("暂无摘要")

    st.divider()

    # ── AI 总结 ──
    st.markdown("### AI 总结")
    _render_ai_summary(paper_key, detail)

    st.divider()

    # ── 期刊信息 ──
    st.markdown("### 期刊信息")
    _render_journal_info(paper_key, detail)

    st.divider()

    # ── 参考文献 ──
    st.markdown("### 参考文献")
    _render_references(paper_key, detail)

    st.divider()

    # ── 施引文献 ──
    st.markdown("### 施引文献")
    _render_citations(paper_key, detail)


def _render_ai_summary(paper_key: str, paper: dict) -> None:
    """
    AI 总结区域（第三阶段升级版）：
      优先触发 RAG 全流程（chunk + 语义检索 + 证据驱动总结）
      无 PDF 时自动降级为摘要兜底
      已生成的结果带证据片段展示
    """
    cache: dict = st.session_state.get("summary_cache", {})

    if paper_key in cache:
        cached = cache[paper_key]
        if isinstance(cached, dict):
            _render_summary_result(cached)
        else:
            st.markdown(cached)
        return

    abstract = paper.get("summary") or paper.get("abstract") or ""
    pdf_url = paper.get("pdf_url") or ""
    arxiv_id = paper.get("arxiv_id") or ""
    has_pdf_source = bool(pdf_url or arxiv_id)

    if has_pdf_source:
        btn_label = "RAG 深度解析（推荐）"
        hint = "将下载 PDF → 切 chunk → AI 语义检索 → 基于证据片段生成深度总结，约需 60~120 秒。"
    else:
        btn_label = "基于摘要生成 AI 解读"
        hint = "该论文暂无开放 PDF，将基于摘要生成轻量解读，约需 5~15 秒。"

    if not abstract.strip() and not has_pdf_source:
        st.caption("暂无摘要和 PDF，无法生成 AI 总结。")
        return

    st.caption(hint)

    if st.button(btn_label, key="gen_summary", type="primary"):
        with st.spinner("AI 总结生成中，请稍候（RAG 流程较慢，请耐心等待）…"):
            result = fetch_rag_summary(paper, top_k=8)
        if "summary_cache" not in st.session_state:
            st.session_state["summary_cache"] = {}
        st.session_state["summary_cache"][paper_key] = result
        st.rerun()


def _render_summary_result(result: dict) -> None:
    """渲染 AI 总结结果（RAG / 全文 / 摘要三种来源），含证据片段展示。"""
    source = result.get("source", "")
    page_count = result.get("page_count", 0)
    pdf_available = result.get("pdf_available", False)
    summary = result.get("summary", "")
    retrieved_chunks = result.get("retrieved_chunks") or []
    total_chunks = result.get("total_chunks", 0)

    # ── 来源标注 ──
    if source == "rag":
        st.success(
            f"RAG 模式｜已解析 PDF 全文（{page_count} 页）"
            f"，从 {total_chunks} 个片段中检索出 {len(retrieved_chunks)} 条证据"
        )
    elif source == "rag_abstract":
        st.info("RAG 模式（基于摘要 chunk）｜未找到可用 PDF，已对摘要做 chunk 检索")
    elif source == "abstract_fallback":
        st.info("摘要模式｜未能获取 PDF，以下为摘要级 AI 解读")
    elif source == "pdf" or source == "pdf_direct":
        st.success(f"全文模式｜已解析 PDF 全文（{page_count} 页）")
    elif source and source.startswith("error"):
        st.warning(f"解析遇到问题（{source}），已降级为摘要解读")

    # ── 总结正文 ──
    st.markdown(summary)

    # ── 证据片段展示（可折叠） ──
    if retrieved_chunks:
        st.divider()
        with st.expander(
            f"查看 RAG 证据片段（共 {len(retrieved_chunks)} 条，按相关度排序）"
        ):
            for chunk in retrieved_chunks:
                cid = chunk.get("chunk_id", "?")
                sec = chunk.get("section", "").upper()
                score = chunk.get("relevance_score", 0)
                text = chunk.get("text", "")
                with st.container(border=True):
                    st.caption(f"片段 {cid}｜章节：{sec}｜相关度：{score}/10")
                    st.markdown(text[:500] + ("…" if len(text) > 500 else ""))


# ─── 期刊信息 ─────────────────────────────────────────────────────────────────


def _render_journal_info(paper_key: str, paper: dict) -> None:
    """期刊信息区域：Crossref 查询，含缓存。"""
    cache: dict = st.session_state.get("journal_cache", {})

    if paper_key in cache:
        _display_journal_info(cache[paper_key])
        return

    doi = paper.get("doi") or ""
    title = paper.get("title") or ""
    if not doi and not title:
        st.caption("暂无 DOI 或标题，无法查询期刊信息")
        return

    if st.button("查询期刊信息", key="load_journal"):
        with st.spinner("查询期刊信息中…"):
            info = fetch_journal_info(paper)
        if "journal_cache" not in st.session_state:
            st.session_state["journal_cache"] = {}
        st.session_state["journal_cache"][paper_key] = info
        st.rerun()


def _display_journal_info(info: dict) -> None:
    """展示期刊信息字段。"""
    source = info.get("source", "")
    if source == "unavailable" or source == "error":
        st.caption("暂无期刊信息（Crossref 未收录）")
        return

    journal_name = info.get("journal_name") or ""
    journal_short = info.get("journal_short") or ""
    publisher = info.get("publisher") or ""
    issn = info.get("issn") or ""
    doc_type = info.get("type") or ""
    is_oa = info.get("is_open_access") or False
    subjects = info.get("subjects") or []
    ref_count = info.get("reference_count_crossref")

    cols = st.columns(2)
    with cols[0]:
        if journal_name:
            st.markdown(
                f"**期刊名称**\n\n{journal_name}"
                + (
                    f"（{journal_short}）"
                    if journal_short and journal_short != journal_name
                    else ""
                )
            )
        if publisher:
            st.markdown(f"**出版商**\n\n{publisher}")
        if issn:
            st.markdown(f"**ISSN**\n\n`{issn}`")
    with cols[1]:
        if doc_type:
            type_label = {
                "journal-article": "期刊论文",
                "proceedings-article": "会议论文",
                "book-chapter": "书章",
                "posted-content": "预印本",
            }.get(doc_type, doc_type)
            st.markdown(f"**文档类型**\n\n{type_label}")
        oa_label = "开放获取 (OA)" if is_oa else "受限访问"
        st.markdown(f"**访问类型**\n\n{oa_label}")
        if ref_count is not None:
            st.markdown(f"**Crossref 被引**\n\n{ref_count}")

    if subjects:
        st.markdown(f"**学科领域**\n\n{'  ·  '.join(subjects)}")


# ─── 参考文献 ─────────────────────────────────────────────────────────────────


def _render_references(paper_key: str, paper: dict) -> None:
    """参考文献区域：Semantic Scholar 真实数据 + DeepSeek AI 候选，含缓存。"""
    cache: dict = st.session_state.get("references_cache", {})

    if paper_key in cache:
        _display_references(cache[paper_key])
        return

    if st.button("加载参考文献", key="load_refs"):
        with st.spinner("正在查询参考文献（可能需要 10~20 秒）…"):
            data = fetch_references(paper)
        if "references_cache" not in st.session_state:
            st.session_state["references_cache"] = {}
        st.session_state["references_cache"][paper_key] = data
        st.rerun()


def _display_references(data: dict) -> None:
    """渲染参考文献列表。"""
    refs = data.get("references") or []
    ai_sugg = data.get("ai_suggestions") or []
    source = data.get("source", "")

    if source == "error":
        st.caption("参考文献查询失败，请稍后重试")
        return

    # ── 真实参考文献 ──
    if refs:
        st.caption(f"共找到 {len(refs)} 条参考文献（来源：Semantic Scholar）")
        _show_ref_list(refs, key_prefix="ref", show_count=5)
    else:
        st.caption("未在 Semantic Scholar 找到参考文献记录")

    # ── AI 推荐候选（仅在真实结果不足时才有） ──
    if ai_sugg:
        st.divider()
        st.markdown("**AI 推荐参考（待核验）**")
        st.caption("以下条目由 AI 根据论文主题推断，已尝试学术数据库核验，仅供参考。")
        _show_ref_list(ai_sugg, key_prefix="ai_ref", show_count=len(ai_sugg))


def _show_ref_list(items: list[dict], key_prefix: str, show_count: int = 5) -> None:
    """通用：渲染一组参考文献/施引文献卡片，默认展示 show_count 条，可展开更多。"""
    expand_key = f"{key_prefix}_expanded"
    is_expanded = st.session_state.get(expand_key, False)

    display = items if is_expanded else items[:show_count]

    for i, item in enumerate(display):
        title = item.get("title") or "（无标题）"
        authors = item.get("authors") or []
        year = item.get("year")
        venue = item.get("venue") or ""
        abs_url = item.get("abs_url") or ""
        doi = item.get("doi") or ""
        ai_flag = item.get("ai_suggested") or False
        verified = item.get("ai_verified") or False

        with st.container(border=True):
            label = f"**{title[:90]}{'…' if len(title) > 90 else ''}**"
            if ai_flag:
                badge = " `AI推荐·已核验`" if verified else " `AI推荐·待核验`"
                label += badge
            st.markdown(label)

            meta = []
            if authors:
                meta.append(authors[0] + (" 等" if len(authors) > 1 else ""))
            if year:
                meta.append(str(year))
            if venue:
                meta.append(venue[:30])
            if meta:
                st.caption("  ·  ".join(meta))

            link = abs_url or (f"https://doi.org/{doi}" if doi else "")
            if link:
                st.markdown(f"[查看原文]({link})")

    if len(items) > show_count:
        if not is_expanded:
            if st.button(f"展开全部 {len(items)} 条", key=f"{key_prefix}_more"):
                st.session_state[expand_key] = True
                st.rerun()
        else:
            if st.button("收起", key=f"{key_prefix}_less"):
                st.session_state[expand_key] = False
                st.rerun()


# ─── 施引文献 ─────────────────────────────────────────────────────────────────


def _render_citations(paper_key: str, paper: dict) -> None:
    """施引文献区域：Semantic Scholar，含缓存。"""
    cache: dict = st.session_state.get("citations_cache", {})

    if paper_key in cache:
        _display_citations(cache[paper_key])
        return

    if st.button("加载施引文献", key="load_cits"):
        with st.spinner("正在查询施引文献（可能需要 10~20 秒）…"):
            data = fetch_citations(paper, limit=20)
        if "citations_cache" not in st.session_state:
            st.session_state["citations_cache"] = {}
        st.session_state["citations_cache"][paper_key] = data
        st.rerun()


def _display_citations(data: dict) -> None:
    """渲染施引文献列表。"""
    cits = data.get("citations") or []
    source = data.get("source", "")

    if source in ("unavailable", "error"):
        st.caption("未找到施引文献记录（Semantic Scholar 未收录或查询失败）")
        return
    if source == "rate_limited":
        st.caption("Semantic Scholar 限流，请稍后再试")
        return

    if cits:
        st.caption(
            f"共找到 {len(cits)} 条施引文献（来源：Semantic Scholar，按年份降序）"
        )
        _show_ref_list(cits, key_prefix="cit", show_count=5)
    else:
        st.caption("暂无施引文献记录")
