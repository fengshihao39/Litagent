"""Litagent - Streamlit 网络层

该模块是 Litagent 的 Streamlit 前端的网络层，专用于网络通信。
"""

import os
from typing import Any, Dict, List

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("LITAGENT_FRONTEND_API_URL", "http://localhost:8000")


def fetch_papers(
    query: str, uploaded_file, search_params: dict
) -> List[Dict[str, Any]]:
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
        return _get_demo_results()
    except ValueError as exc:
        st.toast(f"😢 后端响应解析失败：{exc} 下面展示的是固定的示例数据。")
        return _get_demo_results()


def _get_demo_results() -> List[Dict[str, Any]]:
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
