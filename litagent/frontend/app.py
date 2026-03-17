"""Litagent - Streamlit 应用入口

该模块负责组织 Streamlit 页面布局与交互逻辑。
新增：历史侧边栏、新对话、卡片式结果列表、论文详情页同页切换。

使用样例：
    在项目根目录下运行 `uv run streamlit run litagent/frontend/app.py`。
"""

import datetime
import os

import streamlit as st
from dotenv import load_dotenv

from litagent.frontend.api import fetch_papers
from litagent.frontend.analyze_page import render_analyze_page
from litagent.frontend.components import plot_keyword_freq, plot_year_trend
from litagent.frontend.detail_page import render_detail_page
from litagent.frontend.history_api import create_session, save_search_record
from litagent.frontend.history_sidebar import render_history_sidebar
from litagent.frontend.paper_cards import render_paper_cards
from litagent.frontend.session_state import (
    go_to_search,
    init_session_state,
    set_search_results,
)
from litagent.frontend.utils import to_bibtex

st.set_page_config(page_title="Litagent 文献智能助手", page_icon="📚", layout="wide")

load_dotenv()


# ─── 侧边栏（历史记录，所有页面都显示） ──────────────────────────────────────

render_history_sidebar()

# ─── 初始化 session_state ─────────────────────────────────────────────────────

init_session_state()

# ─── 路由：详情页 ─────────────────────────────────────────────────────────────

if st.session_state["page"] == "detail" and st.session_state["current_paper"]:
    render_detail_page(
        paper=st.session_state["current_paper"],
        all_results=st.session_state.get("search_results", []),
    )
    st.stop()

# ─── 路由：深度解析页 ─────────────────────────────────────────────────────────

if st.session_state["page"] == "analyze":
    render_analyze_page()
    st.stop()

# ─── 路由：搜索页 ─────────────────────────────────────────────────────────────


def _render_header() -> None:
    st.title("📚 Litagent 文献智能助手")
    st.caption("欢迎使用 Litagent 文献智能助手！")
    st.caption("Litagent 可以根据你的关键词和研究主题，自动检索并为你推荐相关的文献。")


def _render_search_form():
    with st.sidebar:
        st.subheader("检索设置")
        with st.form("search_form"):
            query = st.text_input(
                "文献关键词 / 主题",
                placeholder="如：LLM jailbreak",
                value=st.session_state.get("last_query", ""),
            )
            max_results = st.slider("文献返回数量", min_value=5, max_value=20, value=10)

            current_year = datetime.date.today().year
            year_map = {
                "不限": None,
                "近 1 年": current_year - 1,
                "近 3 年": current_year - 3,
                "近 5 年": current_year - 5,
                "近 10 年": current_year - 10,
            }
            time_label = st.selectbox("文献时间范围", options=list(year_map.keys()))

            st.markdown("---")
            use_domain_vocab = st.checkbox("启用领域词汇预置", value=True)
            use_arxiv = st.checkbox("启用 arXiv 默认分类过滤", value=True)

            submitted = st.form_submit_button(
                "开始检索", type="primary", use_container_width=True
            )

        # form 外：本地 PDF 深度解析入口
        st.divider()
        st.markdown("**本地 PDF 深度解析**")
        st.caption("上传本地 PDF，AI 自动生成深度解读")
        if st.button("进入 PDF 深度解析", use_container_width=True, key="go_analyze"):
            st.session_state["page"] = "analyze"
            st.rerun()

    return (
        query,
        max_results,
        year_map,
        time_label,
        use_domain_vocab,
        use_arxiv,
        submitted,
    )


def _build_search_params(
    query, max_results, year_map, time_label, use_domain_vocab, use_arxiv
) -> dict:
    params = {
        "query": query,
        "max_results": max_results,
        "year_from": year_map[time_label],
        "use_domain_vocab": use_domain_vocab,
        "use_arxiv_categories": use_arxiv,
    }
    return {k: v for k, v in params.items() if v is not None}


def _ensure_session(query: str) -> str | None:
    """确保有当前 session_id；没有就新建一个，用搜索词做标题。"""
    sid = st.session_state.get("current_session_id")
    if not sid:
        title = query[:30] if query else "新对话"
        sid = create_session(title)
        st.session_state["current_session_id"] = sid
    return sid


def _render_visualizations(results: list[dict]) -> None:
    """在搜索结果上方显示图表（可折叠）。"""
    with st.expander("📊 可视化统计", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            plot_year_trend(results)
        with col2:
            plot_keyword_freq(results)


def _render_download_all(results: list[dict]) -> None:
    bibtex_all = "\n\n".join(to_bibtex(r) for r in results)
    st.download_button(
        "📥 下载全部 BibTeX 引用",
        bibtex_all,
        file_name="all_references.bib",
        mime="text/plain",
        use_container_width=True,
    )


def main() -> None:
    _render_header()

    (
        query,
        max_results,
        year_map,
        time_label,
        use_domain_vocab,
        use_arxiv,
        submitted,
    ) = _render_search_form()

    # ── 触发搜索 ──────────────────────────────────────────────────────────────
    query_str: str = query or ""
    if submitted and query_str.strip():
        search_params = _build_search_params(
            query_str, max_results, year_map, time_label, use_domain_vocab, use_arxiv
        )
        with st.spinner("🔍 正在全力为你检索相关文献……"):
            results = fetch_papers(query_str, None, search_params)

        if results:
            set_search_results(results, query_str)
            # 保存到历史记录
            sid = _ensure_session(query_str)
            if sid:
                save_search_record(sid, query_str, results)
        else:
            st.warning("未能找到相关文献，请调整关键词重试。")
            st.stop()

    # ── 展示结果 ─────────────────────────────────────────────────────────────
    results = st.session_state.get("search_results", [])

    if not results:
        IMAGE_BACKGROUND = os.getenv(
            "IMAGE_BACKGROUND",
            "https://images.unsplash.com/photo-1524995997946-a1c2e315a42f"
            "?auto=format&fit=crop&w=1400&q=80",
        )
        st.image(IMAGE_BACKGROUND, width=1200)
        return

    _render_visualizations(results)
    _render_download_all(results)
    st.divider()
    render_paper_cards(results)


if __name__ == "__main__":
    main()
