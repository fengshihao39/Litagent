"""Litagent - Streamlit 网络层

该模块是 Litagent 的 Streamlit 前端的网络层，专用于网络通信。
"""

import os
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

from litagent.frontend.demo_data import get_demo_results

load_dotenv()

API_BASE_URL = os.getenv("LITAGENT_FRONTEND_API_URL", "http://localhost:8000")


def fetch_papers(
    query: str, uploaded_file, search_params: dict
) -> list[dict[str, Any]]:
    """该函数向后端发送搜索请求。

    Args:
        query (str): 向后端请求的搜索内容。
        uploaded_file (): 用户上传的论文文件（如果有）。
        search_params (dict): 搜索参数。

    Returns:
        List[Dict[str, Any]]: 后端返回的搜索结果。
    """
    if not query and uploaded_file is None:
        return []

    files = None
    if uploaded_file is not None:
        files = {"file": (uploaded_file.name, uploaded_file.getvalue())}

    try:
        resp = requests.post(
            f"{API_BASE_URL}/search",
            data=search_params,
            files=files,
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("results", payload)
    except requests.RequestException as exc:
        st.toast(f"😢 无法连接到后端！错误：{exc} 下面展示的是固定的示例数据。")
        return get_demo_results()
    except ValueError as exc:
        st.toast(f"😢 后端响应解析失败：{exc} 下面展示的是固定的示例数据。")
        return get_demo_results()
