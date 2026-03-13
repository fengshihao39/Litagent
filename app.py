"""
星火文献 Agent - Streamlit Web 界面
运行方式：
    source venv/bin/activate
    streamlit run xinghuo_agent/app.py
"""

import os
import sys

# 确保包路径正确
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
from agent.literature_agent import LiteratureAgent

# ── 页面配置 ─────────────────────────────────────────────
st.set_page_config(
    page_title="星火文献 Agent",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 全局样式 ─────────────────────────────────────────────
st.markdown(
    """
<style>
/* 聊天气泡 */
.user-bubble {
    background: #e8f4fd;
    border-radius: 12px 12px 4px 12px;
    padding: 10px 16px;
    margin: 4px 0;
    margin-left: 20%;
    color: #1a1a2e;
}
.agent-bubble {
    background: #f0f7f0;
    border-radius: 12px 12px 12px 4px;
    padding: 10px 16px;
    margin: 4px 0;
    margin-right: 20%;
    color: #1a1a2e;
}
/* 来源徽章 */
.badge-arxiv  { background:#b31b1b; color:#fff; padding:2px 7px; border-radius:4px; font-size:12px; }
.badge-s2     { background:#1857a4; color:#fff; padding:2px 7px; border-radius:4px; font-size:12px; }
.badge-ieee   { background:#00629b; color:#fff; padding:2px 7px; border-radius:4px; font-size:12px; }
.badge-unknown{ background:#888;    color:#fff; padding:2px 7px; border-radius:4px; font-size:12px; }
/* 快捷按钮区 */
.stButton>button {
    border-radius: 8px;
    font-size: 13px;
}
</style>
""",
    unsafe_allow_html=True,
)


# ── Session State 初始化 ─────────────────────────────────
def _init_state():
    if "agent" not in st.session_state:
        st.session_state.agent = LiteratureAgent()
    if "messages" not in st.session_state:
        # 每条消息: {"role": "user"/"assistant", "content": str}
        st.session_state.messages = []
    if "paper_cache" not in st.session_state:
        # 同步 agent 内部的 paper_cache，用于显示快捷按钮
        st.session_state.paper_cache = {}


_init_state()

agent: LiteratureAgent = st.session_state.agent


# ── 侧边栏 ───────────────────────────────────────────────
with st.sidebar:
    st.title("🔬 星火文献 Agent")
    st.caption("西安电子科技大学 · 第37届星火杯")

    st.markdown("---")
    st.subheader("数据来源")
    st.markdown(
        "- 📄 **arXiv**\n- 🔍 **Semantic Scholar**\n- ⚡ **IEEE Xplore**（Key 激活后）"
    )

    st.markdown("---")
    st.subheader("使用提示")
    with st.expander("指令示例", expanded=True):
        examples = [
            ("搜索论文", "transformer 雷达目标检测"),
            ("解析论文", "分析第1篇"),
            ("对比分析", "对比 1 2 3"),
            ("生成综述", "综述 雷达信号处理"),
            ("获取引用", "引用 2"),
        ]
        for label, cmd in examples:
            if st.button(
                f"{label}: {cmd}", key=f"ex_{label}", use_container_width=True
            ):
                st.session_state["prefill"] = cmd

    st.markdown("---")
    if st.button("🗑️ 清空对话历史", use_container_width=True):
        agent.clear_history()
        st.session_state.messages = []
        st.session_state.paper_cache = {}
        st.rerun()

    # 已缓存论文列表
    if agent.paper_cache:
        st.markdown("---")
        st.subheader("已检索论文")
        for idx, paper in agent.paper_cache.items():
            src = paper.get("source", "unknown")
            badge_class = {
                "arxiv": "badge-arxiv",
                "semantic_scholar": "badge-s2",
                "ieee": "badge-ieee",
            }.get(src, "badge-unknown")
            badge_label = {
                "arxiv": "arXiv",
                "semantic_scholar": "S2",
                "ieee": "IEEE",
            }.get(src, src.upper())
            title_short = paper.get("title", "?")[:40]
            st.markdown(
                f"**{idx}.** <span class='{badge_class}'>{badge_label}</span> {title_short}...",
                unsafe_allow_html=True,
            )


# ── 主界面 ───────────────────────────────────────────────
st.title("星火文献 Agent")
st.caption("多源科研文献搜索与深度解析 · 电子信息 / AI / 雷达信号处理")

# 快捷操作按钮（当有搜索结果时显示）
if agent.paper_cache:
    st.markdown("**快捷操作：**")
    cols = st.columns(5)
    with cols[0]:
        if st.button("🔍 分析第1篇"):
            st.session_state["prefill"] = "分析第1篇"
    with cols[1]:
        if st.button("📊 对比前3篇"):
            st.session_state["prefill"] = "对比 1 2 3"
    with cols[2]:
        if st.button("📝 生成综述"):
            st.session_state["prefill"] = "综述"
    with cols[3]:
        if st.button("📎 引用第1篇"):
            st.session_state["prefill"] = "引用 1"
    with cols[4]:
        if st.button("📎 引用第2篇"):
            st.session_state["prefill"] = "引用 2"

# 显示历史消息
chat_container = st.container()
with chat_container:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🔬"):
                st.markdown(msg["content"])

# 输入框
prefill_value = st.session_state.pop("prefill", "")
user_input = st.chat_input(
    "输入指令（如：搜索 transformer 目标检测，分析第1篇，对比 1 2 3 ...）",
)

# 如果有预填值（来自侧边栏按钮），模拟提交
if prefill_value and not user_input:
    user_input = prefill_value

if user_input:
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # 调用 agent
    with st.chat_message("assistant", avatar="🔬"):
        with st.spinner("思考中..."):
            try:
                response = agent.chat(user_input)
            except Exception as e:
                response = f"[出错了] {e}"

        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})

    # 同步 paper_cache 到 session（用于侧边栏显示）
    st.session_state.paper_cache = dict(agent.paper_cache)

    st.rerun()
