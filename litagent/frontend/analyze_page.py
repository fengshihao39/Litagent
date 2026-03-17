"""
Litagent - 本地 PDF 深度解析结果页

页面布局（单独新建，不复用搜索结果页）：
  左侧：论文概览（基础信息 + 章节导航 + 元数据）
  右侧（标签页）：
    Tab1：结构化解读（8维 + 证据片段联动）
    Tab2：章节原文（6章节可切换浏览）
    Tab3：答辩辅助（4种格式）
    Tab4：深度追问（问答）
"""

from __future__ import annotations

import streamlit as st

from litagent.frontend.analyze_api import ask_on_paper, upload_and_analyze_pdf


def render_analyze_page() -> None:
    """深度解析结果页入口：先上传文件，再展示结果。"""

    # ── 返回按钮 ──
    if st.button("← 返回搜索", type="secondary", key="analyze_back"):
        st.session_state["page"] = "search"
        # 清除解析结果，允许重新上传
        st.session_state.pop("analyze_result", None)
        st.rerun()

    st.divider()

    # ── 检查是否已有解析结果 ──
    result = st.session_state.get("analyze_result")

    if result is None:
        _render_upload_form()
    else:
        _render_analysis_result(result)


# ─── 上传表单 ────────────────────────────────────────────────────────────────


def _render_upload_form() -> None:
    """渲染 PDF 上传表单。"""
    st.markdown("## 本地 PDF 深度解析")
    st.markdown(
        "上传本地学术论文 PDF，AI 将自动提取基础信息、生成结构化解读、"
        "输出答辩辅助材料，并支持深度追问。\n\n"
        "**支持中文和英文学术论文。**"
    )

    uploaded = st.file_uploader(
        "选择 PDF 文件（最大 100MB）",
        type=["pdf"],
        key="pdf_uploader",
        help="支持中英文论文，中文论文会自动识别章节结构。",
    )

    force = st.checkbox(
        "强制重新解析（忽略缓存）",
        value=False,
        key="force_reanalyze",
        help="如果曾经上传过同一文件，默认会使用缓存加速。勾选此项强制重新解析。",
    )

    if uploaded is not None:
        st.info(
            f"已选择：**{uploaded.name}**（{uploaded.size / 1024:.1f} KB）\n\n"
            "点击下方按钮开始深度解析，大文件需要 2~5 分钟。"
        )

        if st.button("开始深度解析", type="primary", key="start_analyze"):
            pdf_bytes = uploaded.read()
            with st.spinner(
                "正在解析 PDF…\n\n"
                "（流程：PDF解析 → Chunk切分 → 语义检索 → AI解读 → 答辩辅助，约需 2~5 分钟）"
            ):
                result = upload_and_analyze_pdf(
                    pdf_bytes=pdf_bytes,
                    filename=uploaded.name,
                    force_reanalyze=force,
                )

            if result is None:
                st.error("解析失败，请检查后端服务是否运行，或尝试重新上传。")
            else:
                st.session_state["analyze_result"] = result
                st.success("解析完成！")
                st.rerun()


# ─── 解析结果展示 ────────────────────────────────────────────────────────────


def _render_analysis_result(result: dict) -> None:
    """渲染完整深度解析结果页。"""

    # 顶部：文件信息 + 重新上传按钮
    filename = result.get("filename") or "未知文件"
    page_count = result.get("page_count", 0)
    char_count = result.get("char_count", 0)
    is_chinese = result.get("is_chinese", False)
    total_chunks = result.get("total_chunks", 0)

    lang_label = "中文论文" if is_chinese else "英文论文"
    st.caption(
        f"**{filename}** ｜ {page_count} 页 ｜ {char_count:,} 字符 ｜ "
        f"{lang_label} ｜ 切分 {total_chunks} 个语义片段"
    )

    col_reupload, _ = st.columns([1, 4])
    with col_reupload:
        if st.button("重新上传", key="reupload"):
            st.session_state.pop("analyze_result", None)
            st.rerun()

    st.divider()

    # 双栏布局：左侧概览，右侧标签页
    left_col, right_col = st.columns([1, 2], gap="large")

    with left_col:
        _render_left_panel(result)

    with right_col:
        _render_right_panel(result)


# ─── 左侧概览 ────────────────────────────────────────────────────────────────


def _render_left_panel(result: dict) -> None:
    """左侧：基础信息 + 章节导航。"""
    basic = result.get("basic_info") or {}

    title = basic.get("title") or result.get("filename") or "未知标题"
    authors = basic.get("authors") or []
    year = basic.get("year") or ""
    venue = basic.get("venue") or ""
    keywords = basic.get("keywords") or []
    page_count = basic.get("page_count") or result.get("page_count", 0)
    abstract = basic.get("abstract") or ""

    # ── 标题 ──
    st.markdown(f"### {title[:80]}{'…' if len(title) > 80 else ''}")

    # ── 元数据 ──
    if year:
        st.markdown(f"**年份** {year}")
    if venue:
        st.markdown(f"**来源** {venue[:40]}")
    if page_count:
        st.markdown(f"**页数** {page_count} 页")
    if authors:
        st.markdown("**作者**")
        for a in authors[:5]:
            st.caption(a)
        if len(authors) > 5:
            st.caption(f"… 共 {len(authors)} 位")

    if keywords:
        st.divider()
        st.markdown("**关键词**")
        st.write("  ".join(f"`{k}`" for k in keywords[:10]))

    if abstract:
        st.divider()
        st.markdown("**摘要**")
        # 摘要较长，默认折叠
        with st.expander("展开摘要", expanded=False):
            st.write(abstract)

    # ── 章节导航 ──
    st.divider()
    st.markdown("**章节导航**")
    sections = result.get("sections") or {}
    section_labels = {
        "abstract": "摘要 / Abstract",
        "introduction": "引言 / 绪论",
        "method": "方法 / 核心方法",
        "experiment": "实验 / 仿真",
        "result": "结果 / 性能分析",
        "conclusion": "结论 / 总结",
    }
    available = [k for k, v in sections.items() if v.strip()]
    if available:
        for sec in section_labels:
            if sec in available:
                st.caption(f"✓ {section_labels[sec]}")
            else:
                st.caption(f"– {section_labels[sec]}（未提取）")
    else:
        st.caption("章节结构未提取（可能是扫描件）")


# ─── 右侧标签页 ──────────────────────────────────────────────────────────────


def _render_right_panel(result: dict) -> None:
    """右侧：4个标签页。"""
    paper_key = result.get("paper_key") or ""

    tab1, tab2, tab3, tab4 = st.tabs(["结构化解读", "章节原文", "答辩辅助", "深度追问"])

    with tab1:
        _render_tab_structured(result)

    with tab2:
        _render_tab_sections(result)

    with tab3:
        _render_tab_defense(result)

    with tab4:
        _render_tab_qa(paper_key)


# ── Tab1：结构化解读 ─────────────────────────────────────────────────────────


def _render_tab_structured(result: dict) -> None:
    """结构化解读：8维分析 + 证据片段联动。"""
    structured = result.get("structured") or ""
    retrieved = result.get("retrieved") or []

    if not structured:
        st.caption("结构化解读暂不可用")
        return

    st.markdown("#### 全文结构化解读")
    st.markdown(structured)

    # ── 证据片段联动 ──
    if retrieved:
        st.divider()
        with st.expander(
            f"查看支撑证据片段（共 {len(retrieved)} 条，按相关度排序）",
            expanded=False,
        ):
            _render_evidence_chunks(retrieved)


def _render_evidence_chunks(chunks: list[dict]) -> None:
    """渲染证据片段列表。"""
    section_labels = {
        "abstract": "摘要",
        "introduction": "引言",
        "method": "方法",
        "experiment": "实验",
        "result": "结果",
        "conclusion": "结论",
        "full_text": "全文",
    }
    for chunk in chunks:
        cid = chunk.get("chunk_id", "?")
        sec = chunk.get("section", "")
        sec_label = section_labels.get(sec, sec.upper())
        score = chunk.get("relevance_score", 0)
        text = chunk.get("text", "")

        with st.container(border=True):
            st.caption(f"片段 **{cid}** ｜ 章节：{sec_label} ｜ 相关度：{score}/10")
            st.markdown(text[:600] + ("…" if len(text) > 600 else ""))


# ── Tab2：章节原文 ───────────────────────────────────────────────────────────


def _render_tab_sections(result: dict) -> None:
    """章节原文：6章节可切换浏览。"""
    sections = result.get("sections") or {}
    section_labels = {
        "abstract": "摘要 / Abstract",
        "introduction": "引言 / 绪论",
        "method": "方法 / 核心方法",
        "experiment": "实验 / 仿真",
        "result": "结果 / 性能分析",
        "conclusion": "结论 / 总结",
    }

    available = {k: v for k, v in sections.items() if v.strip()}
    if not available:
        st.caption("未能提取章节内容（可能是扫描件或加密 PDF）")
        return

    st.markdown("#### 章节内容导览")
    st.caption("以下是从 PDF 中提取的各章节原文（最多 3000 字/章节）")

    for sec_key, label in section_labels.items():
        content = available.get(sec_key, "")
        if not content:
            continue
        with st.expander(f"**{label}**（{len(content)} 字）", expanded=False):
            st.markdown(content)


# ── Tab3：答辩辅助 ───────────────────────────────────────────────────────────


def _render_tab_defense(result: dict) -> None:
    """答辩辅助：4种格式展示。"""
    defense = result.get("defense") or {}

    one_sentence = defense.get("one_sentence") or ""
    detailed = defense.get("detailed") or ""
    ppt_points = defense.get("ppt_points") or []
    likely_questions = defense.get("likely_questions") or []

    if not defense or (not one_sentence and not detailed):
        st.caption("答辩辅助暂不可用")
        return

    st.markdown("#### 答辩辅助材料")

    # ── 一句话总结 ──
    if one_sentence:
        st.markdown("**一句话总结版**")
        st.info(one_sentence)

    # ── 详细汇报版 ──
    if detailed:
        st.markdown("**详细汇报版**（200字）")
        with st.container(border=True):
            st.markdown(detailed)

    # ── PPT 要点版 ──
    if ppt_points:
        st.markdown("**PPT 要点版**")
        for i, point in enumerate(ppt_points, 1):
            st.markdown(f"{i}. {point}")

    # ── 可能追问问题版 ──
    if likely_questions:
        st.divider()
        st.markdown("**可能被追问的问题**")
        for i, q in enumerate(likely_questions, 1):
            with st.container(border=True):
                st.markdown(f"**Q{i}.** {q}")

    # ── 导出提示 ──
    st.divider()
    st.caption("提示：可在浏览器中右键 → 打印 → 另存为 PDF 来导出答辩材料。")


# ── Tab4：深度追问 ───────────────────────────────────────────────────────────


def _render_tab_qa(paper_key: str) -> None:
    """深度追问问答区域。"""
    if not paper_key:
        st.caption("paper_key 缺失，无法进行问答")
        return

    st.markdown("#### 深度追问")
    st.caption(
        "针对本篇论文提问，AI 将基于全文语义检索作答。\n\n"
        "示例：「这篇论文的核心创新是什么？」「第三章的方法和第四章有什么区别？」"
    )

    # 预设快速问题
    preset_questions = [
        "这篇论文的核心创新点是什么？",
        "论文提出的方法和已有方法相比有什么优势？",
        "实验是如何验证方法有效性的？",
        "这篇论文有哪些局限性和未来展望？",
        "论文中的关键公式/模型是什么？请用通俗语言解释。",
    ]

    st.markdown("**快速提问**")
    preset_cols = st.columns(2)
    for i, pq in enumerate(preset_questions):
        col = preset_cols[i % 2]
        with col:
            if st.button(pq[:30] + "…" if len(pq) > 30 else pq, key=f"preset_q_{i}"):
                st.session_state["qa_question_input"] = pq

    st.divider()

    # 自由输入
    question = st.text_area(
        "输入你的问题",
        value=st.session_state.get("qa_question_input", ""),
        height=80,
        key="qa_input_area",
        placeholder="例如：请解释一下论文中的信号模型是如何建立的？",
    )

    col_ask, col_clear = st.columns([2, 1])
    with col_ask:
        ask_btn = st.button("提问", type="primary", key="ask_btn")
    with col_clear:
        if st.button("清空对话", key="clear_qa"):
            st.session_state.pop("qa_history", None)
            st.session_state.pop("qa_question_input", None)
            st.rerun()

    if ask_btn and question.strip():
        with st.spinner("AI 正在检索论文内容并作答…"):
            response = ask_on_paper(
                paper_key=paper_key,
                question=question.strip(),
                top_k=5,
            )

        # 存入对话历史
        if "qa_history" not in st.session_state:
            st.session_state["qa_history"] = []
        st.session_state["qa_history"].append(
            {
                "question": question.strip(),
                "answer": response.get("answer", ""),
                "evidence": response.get("evidence", []),
            }
        )
        # 清空输入框
        st.session_state.pop("qa_question_input", None)
        st.rerun()

    # ── 对话历史展示（最新在前）──
    history = st.session_state.get("qa_history") or []
    if history:
        st.divider()
        st.markdown("**对话记录**")
        for i, qa in enumerate(reversed(history)):
            idx = len(history) - i
            with st.container(border=True):
                st.markdown(f"**Q{idx}：{qa['question']}**")
                st.markdown(qa["answer"])

                evidence = qa.get("evidence") or []
                if evidence:
                    with st.expander(
                        f"查看支撑证据（{len(evidence)} 条）", expanded=False
                    ):
                        _render_evidence_chunks(evidence)
