"""Litagent - Streamlit 应用入口

该模块负责组织 Streamlit 页面布局与交互逻辑。

使用样例：
    在项目根目录下运行 `PYTHONPATH=. streamlit run Litagent/frontend/app.py`。
"""

import datetime

import streamlit as st
from Litagent.frontend.api import fetch_papers
from Litagent.frontend.utils import to_bibtex
from Litagent.frontend.components import plot_year_trend, plot_keyword_freq

st.set_page_config(page_title="Litagent 文献智能助手", page_icon="📚", layout="wide")


def main():
    """构建 Litagent Streamlit 前端页面并处理交互。"""
    st.title("📚 Litagent 文献智能助手")
    st.caption("欢迎使用 Litagent 文献智能助手！")
    st.caption("Litagent 可以根据你的关键词和研究主题，以及正在研究的文献内容，自动检索并为你推荐相关的文献。")
    st.caption("在左侧设置你想要检索的文献关键词或主题，并设置文献的返回数量和时间范围，即可开始检索。")
    st.caption("你也可以上传自己正在研究的文献列表（支持 `.csv`、`.json`、`.bib` 和 `.bibtex` 格式），让 AI 自动分析你的研究主题。")

    with st.sidebar:
        st.subheader("检索设置")
        with st.form("search_form"):
            query = st.text_input("文献关键词 / 主题", placeholder="如：LLM jailbreak")
            uploaded_file = st.file_uploader(
                "上传本地文献数据", type=["csv", "json", "bib", "bibtex"]
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

            # 我们在后端已经优化了搜索方案，这个 Checkbox 应当说是已经没啥用的了，但还是留着吧。
            use_domain_vocab = st.checkbox("启用领域词汇预置", value=True)

            use_arxiv = st.checkbox("启用 arXiv 默认分类过滤", value=True)

            submitted = st.form_submit_button(
                "开始检索", type="primary", use_container_width=True
            )

    if not submitted:
        st.image(
            "https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?auto=format&fit=crop&w=1400&q=80",
            width=1200,
        )  # TODO Image 的 URL 转到配置里，不要明文写死
        return

    # 统一构造参数并过滤空值，避免后端解析异常
    with st.spinner("🔍 正在全力为你检索相关文献……"):
        search_params = {
            "query": query,
            "max_results": max_results,
            "year_from": year_map[time_label],
            "use_domain_vocab": use_domain_vocab,
            "use_arxiv_categories": use_arxiv,
        }
        search_params = {k: v for k, v in search_params.items() if v is not None}

        results = fetch_papers(query, uploaded_file, search_params)

    if not results:
        st.warning("未能找到相关文献，请调整关键词重试。")
        return

    st.success(f"🎉 检索完成！共返回 {len(results)} 条相关文献。")

    bibtex_all = "\n\n".join(to_bibtex(r) for r in results)
    st.download_button(
        "📥 下载全部 BibTeX 引用",
        bibtex_all,
        file_name="all_references.bib",
        mime="text/plain",
        use_container_width=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        plot_year_trend(results)
    with col2:
        plot_keyword_freq(results)

    st.divider()

    for idx, paper in enumerate(results):
        with st.expander(
            f"📄 {paper.get('title', '未命名')} ({paper.get('year', '未知')})"
        ):
            st.write(paper.get("abstract", "暂无摘要"))

            meta_cols = st.columns(4)
            meta_cols[0].metric("年份", paper.get("year", ""))
            meta_cols[1].metric("作者数", len(paper.get("authors", [])))
            meta_cols[2].metric("关键词数", len(paper.get("keywords", [])))
            meta_cols[3].metric("来源", paper.get("venue", ""))

            authors = ", ".join(paper.get("authors", ["未知作者"]))
            keywords = ", ".join(paper.get("keywords", ["无"]))
            doi = paper.get("doi", "无")

            st.write("**👤 作者**", authors)
            st.write("**🏷️ 关键词**", keywords)
            st.write("**🔗 DOI**", doi)

            bibtex = to_bibtex(paper)
            st.code(bibtex, language="bibtex")

            st.download_button(
                "下载本条 BibTeX",
                bibtex,
                file_name=f"{paper.get('year', 'year')}_{paper.get('title', 'ref')}.bib".replace(
                    " ", "_"
                ),
                mime="text/plain",
                key=f"dl_{idx}",
            )


if __name__ == "__main__":
    main()
