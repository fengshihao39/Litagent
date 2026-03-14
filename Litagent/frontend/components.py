"""Litagent - Streamlit 展示组件

该模块承载图表和统计类组件，供 Streamlit 前端页面复用。
"""

from typing import Any, Dict, List

import pandas as pd
import streamlit as st


def plot_year_trend(results: List[Dict[str, Any]]):
    """绘制文献出版年份趋势。

    Args:
        results (List[Dict[str, Any]]): 论文结果列表。
    """
    years = [r.get("year") for r in results if r.get("year")]
    if not years:
        st.info("缺少年份信息，无法绘制年份趋势图。")
        return

    df = pd.DataFrame(years, columns=["year"])
    trend = df.value_counts().reset_index(name="count").set_index("year").sort_index()
    st.markdown("##### 出版趋势")
    st.line_chart(trend)


def plot_keyword_freq(results: List[Dict[str, Any]]):
    """绘制关键词频率 Top 12 柱状图。

    Args:
        results (List[Dict[str, Any]]): 论文结果列表。
    """
    keywords = [kw for r in results for kw in r.get("keywords", [])]
    if not keywords:
        st.info("缺少关键词信息，无法绘制关键词数量统计图。")
        return

    df = pd.Series(keywords).value_counts().head(12)
    st.markdown("##### 关键词频率 Top 12")
    st.bar_chart(df, horizontal=True)
