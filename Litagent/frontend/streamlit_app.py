"""Litagent - Streamlit 前端

该模块是 Litagent 的基于 Streamlit 的前端。

使用样例：

    在项目根目录下运行 `PYTHONPATH=. streamlit run Litagent/frontend/streamlit_app.py`。
"""

import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import matplotlib.pyplot as plt
import pandas as pd
import requests
import streamlit as st

from Litagent.config.settings import get_api_base_url

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

st.set_page_config(
    page_title="Litagent 文献智能助手",
    page_icon="📚",
    layout="wide",
)

API_BASE_URL = get_api_base_url()


def call_backend(
    query: str,
    uploaded_file,
    max_results: int = 10,
    year_from: int | None = None,
    use_domain_vocab: bool = True,
    use_arxiv_categories: bool = True,
) -> List[Dict[str, Any]]:
    """Send query/file to backend API; fall back to demo data on failure."""
    if not query and uploaded_file is None:
        return []

    files = None
    data = {
        "query": query,
        "max_results": max_results,
        "use_domain_vocab": use_domain_vocab,
        "use_arxiv_categories": use_arxiv_categories,
    }
    if year_from is not None:
        data["year_from"] = year_from
    if uploaded_file is not None:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}

    try:
        resp = requests.post(
            f"{API_BASE_URL}/search",
            data=data,
            files=files,
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        # Expect payload like {"results": [...]} or plain list
        return payload.get("results", payload)
    except Exception:
        st.warning("接口不可用，使用演示数据展示界面效果。")
        return demo_results()


def demo_results() -> List[Dict[str, Any]]:
    return [
        {
            "title": "Transformer-based Literature Review Agent",
            "abstract": "We propose an agentic system that retrieves, ranks, and summarizes papers for rapid review.",
            "authors": ["Li Wei", "Ana Gomez", "Rahul Iyer"],
            "year": 2024,
            "keywords": ["LLM", "retrieval", "summarization", "automation"],
            "venue": "ACL",
            "doi": "10.1234/acl-demo-24",
        },
        {
            "title": "Scientific Document Understanding with Multimodal Models",
            "abstract": "A model that fuses text, layout, and figures to improve downstream scholarly tasks.",
            "authors": ["Chen Yu", "Maria Rossi"],
            "year": 2023,
            "keywords": ["multimodal", "vision-language", "scholar"],
            "venue": "NeurIPS",
            "doi": "10.5555/nips-mm-23",
        },
        {
            "title": "Trends in Automated Bibliography Generation",
            "abstract": "Survey of toolchains that convert structured metadata to BibTeX and CSL-JSON.",
            "authors": ["Smith John"],
            "year": 2021,
            "keywords": ["citation", "bibtex", "tooling"],
            "venue": "JASIST",
            "doi": "10.7777/jasist-21",
        },
    ]


def to_bibtex(entry: Dict[str, Any]) -> str:
    authors = entry.get("authors") or []
    author_field = " and ".join(authors)
    year = entry.get("year", "")
    first_author_token = authors[0].split()[-1].lower() if authors else "anon"
    key = f"{first_author_token}{year}"
    lines = [
        f"@article{{{key},",
        f"  title={{ {entry.get('title', '')} }},",
        f"  author={{ {author_field} }},",
        f"  year={{ {year} }},",
        f"  journal={{ {entry.get('venue', '')} }},",
        f"  doi={{ {entry.get('doi', '')} }},",
        "}",
    ]
    return "\n".join(lines)


def render_header():
    st.title("文献智能助手")
    st.caption("上传文献或输入关键词，实时获取分析、摘要、引用及图表。")


def render_controls():
    with st.sidebar:
        st.subheader("检索设置")
        query = st.text_input(
            "文献关键词 / 主题", placeholder="如：large language model for science"
        )
        uploaded_file = st.file_uploader(
            "上传本地文献数据（CSV/JSON/BibTeX）", type=["csv", "json", "bib", "bibtex"]
        )

        max_results = st.slider("返回数量", min_value=5, max_value=20, value=10, step=1)

        time_options = {
            "不限": None,
            "近1年": 2025,
            "近3年": 2023,
            "近5年": 2021,
            "近10年": 2016,
        }
        time_label = st.selectbox(
            "时间范围", options=list(time_options.keys()), index=0
        )
        year_from = time_options[time_label]

        st.markdown("---")
        st.subheader("检索偏置开关")
        use_domain_vocab = st.checkbox(
            "启用领域词汇预置（雷达/AI/信号处理）",
            value=True,
        )
        use_arxiv_categories = st.checkbox(
            "启用 arXiv 默认分类过滤",
            value=True,
        )

        api_hint = textwrap.dedent(
            f"""
            当前 API: `{API_BASE_URL}/search`
            · 支持关键词检索
            · 支持文件上传
            """
        )
        st.code(api_hint, language="text")
        run = st.button("开始分析", type="primary", use_container_width=True)
    return (
        query,
        uploaded_file,
        run,
        max_results,
        year_from,
        use_domain_vocab,
        use_arxiv_categories,
    )


def render_results(results: List[Dict[str, Any]]):
    if not results:
        st.info("输入关键词或上传文件后点击“开始分析”。")
        return

    st.success(f"共返回 {len(results)} 条文献。")

    bibtex_all = "\n\n".join(to_bibtex(r) for r in results)
    st.download_button(
        "下载 BibTeX 引用清单",
        bibtex_all,
        file_name="references.bib",
        mime="text/plain",
        use_container_width=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        plot_year_trend(results)
    with col2:
        plot_keyword_freq(results)

    st.divider()
    for paper in results:
        with st.expander(
            f"{paper.get('title', '未命名')} · {paper.get('year', '')}", expanded=False
        ):
            st.write(paper.get("abstract", "暂无摘要"))
            meta_cols = st.columns(4)
            meta_cols[0].metric("年份", paper.get("year", ""))
            meta_cols[1].metric("作者数", len(paper.get("authors", [])))
            meta_cols[2].metric("关键词数", len(paper.get("keywords", [])))
            meta_cols[3].metric("来源", paper.get("venue", ""))

            st.write("**作者**", ", ".join(paper.get("authors", [])))
            st.write("**关键词**", ", ".join(paper.get("keywords", [])))
            st.write("**DOI**", paper.get("doi", ""))

            bibtex = to_bibtex(paper)
            st.code(bibtex, language="bibtex")
            st.download_button(
                "下载本条 BibTeX",
                bibtex,
                file_name=f"{paper.get('year', '')}_{paper.get('title', 'ref')}.bib".replace(
                    " ", "_"
                ),
                mime="text/plain",
                key=f"dl-{paper.get('title', '')}",
            )


def plot_year_trend(results: List[Dict[str, Any]]):
    years = [r.get("year") for r in results if r.get("year")]
    if not years:
        st.info("缺少年份信息，无法绘制趋势图。")
        return
    df = pd.DataFrame(years, columns=["year"])
    trend = df.value_counts().reset_index(name="count").sort_values("year")
    fig, ax = plt.subplots()
    ax.plot(trend["year"], trend["count"], marker="o", color="#1f77b4")
    ax.set_title("出版趋势")
    ax.set_xlabel("年份")
    ax.set_ylabel("数量")
    ax.grid(alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_keyword_freq(results: List[Dict[str, Any]]):
    keywords = []
    for r in results:
        keywords.extend(r.get("keywords", []))
    if not keywords:
        st.info("缺少关键词信息，无法绘制关键词频率。")
        return
    df = pd.Series(keywords).value_counts().head(12)
    fig, ax = plt.subplots()
    df.sort_values().plot.barh(color="#ff7f0e", ax=ax)
    ax.set_title("关键词频率 Top12")
    ax.set_xlabel("出现次数")
    st.pyplot(fig, use_container_width=True)


def main():
    render_header()
    (
        query,
        uploaded_file,
        run,
        max_results,
        year_from,
        use_domain_vocab,
        use_arxiv_categories,
    ) = render_controls()
    if run:
        with st.spinner("分析中，请稍候..."):
            results = call_backend(
                query,
                uploaded_file,
                max_results=max_results,
                year_from=year_from,
                use_domain_vocab=use_domain_vocab,
                use_arxiv_categories=use_arxiv_categories,
            )
        render_results(results)
    else:
        st.image(
            "https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?auto=format&fit=crop&w=1400&q=80",
            caption="输入关键词即可开始探索文献。",
            use_column_width=True,
        )


if __name__ == "__main__":
    main()
