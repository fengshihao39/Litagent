"""
IEEE Xplore 搜索模块
使用 Metadata Search API
Key 状态 waiting 时会返回 403，激活后自动生效
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from Litagent.config.settings import get_ieee_api_key

IEEE_API_BASE = "https://ieeexploreapi.ieee.org/api/v1/search/articles"

IEEE_API_KEY = get_ieee_api_key(required=False)

# 西电三大方向对应的 IEEE 分类词
IEEE_QUERY_TERMS = {
    "电子信息": "signal processing OR electronic information OR communications",
    "人工智能": "artificial intelligence OR machine learning OR deep learning",
    "雷达信号处理": "radar signal processing OR SAR OR target detection",
}


def search_papers(
    query: str,
    max_results: int = 8,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> List[Dict]:
    """
    使用 IEEE Xplore Metadata Search API 搜索论文

    参数:
        query       : 搜索关键词（英文）
        max_results : 返回数量（最多 25）
        start_year  : 起始年份过滤
        end_year    : 截止年份过滤

    返回:
        统一格式的论文列表
    """
    if not IEEE_API_KEY:
        return [
            {
                "error": "IEEE API Key 未配置，请在 .env 中设置 IEEE_API_KEY。",
                "source": "ieee",
            }
        ]

    params = {
        "apikey": IEEE_API_KEY,
        "querytext": query,
        "max_records": min(max_results, 25),
        "start_record": 1,
        "sort_order": "desc",
        "sort_field": "article_number",
        "format": "json",
    }

    if start_year:
        params["start_year"] = start_year
    if end_year:
        params["end_year"] = end_year

    url = f"{IEEE_API_BASE}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return [
                {
                    "error": "IEEE API Key 尚未激活（状态 waiting），请等待审核通过后再试。",
                    "source": "ieee",
                }
            ]
        elif e.code == 429:
            return [
                {
                    "error": "IEEE API 今日调用次数已达上限（200次/天）。",
                    "source": "ieee",
                }
            ]
        else:
            return [
                {
                    "error": f"IEEE API 请求失败 HTTP {e.code}: {e.reason}",
                    "source": "ieee",
                }
            ]
    except Exception as e:
        return [{"error": f"IEEE 网络请求失败: {e}", "source": "ieee"}]

    return _parse_response(content)


def _parse_response(json_content: str) -> List[Dict]:
    """解析 IEEE API 返回的 JSON"""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"IEEE 响应解析失败: {e}", "source": "ieee"}]

    articles = data.get("articles", [])
    if not articles:
        return []

    papers = []
    for a in articles:
        title = a.get("title", "").strip()
        abstract = a.get("abstract", "").strip()

        if not title:
            continue

        # 作者
        authors_data = a.get("authors", {}).get("authors", [])
        authors = [
            auth.get("full_name", "") for auth in authors_data if auth.get("full_name")
        ]

        # 发表时间
        pub_year = str(a.get("publication_year") or "")
        published = f"{pub_year}-01-01" if pub_year else "unknown"

        # 期刊/会议
        venue = a.get("publication_title", "")

        # 链接
        doi = a.get("doi", "")
        article_number = a.get("article_number", "")
        abs_url = a.get("html_url") or (
            f"https://ieeexplore.ieee.org/document/{article_number}"
            if article_number
            else ""
        )
        pdf_url = a.get("pdf_url", "")

        # 关键词
        kw_data = a.get("index_terms", {})
        keywords = []
        for kw_group in kw_data.values():
            keywords.extend(kw_group.get("terms", []))

        papers.append(
            {
                "source": "ieee",
                "paper_id": article_number,
                "arxiv_id": "",
                "doi": doi,
                "title": title,
                "authors": authors,
                "published": published,
                "year": pub_year,
                "venue": venue,
                "categories": keywords[:5],
                "summary": abstract,
                "tldr": "",
                "citation_count": 0,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )

    return papers


def format_paper_brief(paper: Dict, index: Optional[int] = None) -> str:
    """格式化单篇 IEEE 论文"""
    if "error" in paper:
        return f"[IEEE] {paper['error']}"

    prefix = f"[{index}] " if index is not None else ""
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " 等"

    venue_str = f"  |  {paper['venue']}" if paper.get("venue") else ""

    return (
        f"{prefix}**{paper['title']}**\n"
        f"   作者: {authors_str}\n"
        f"   时间: {paper['published']}{venue_str}\n"
        f"   来源: IEEE Xplore  |  链接: {paper['abs_url']}\n"
        f"   摘要: {paper['summary'][:200]}...\n"
    )


# ── 测试 ─────────────────────────────────────────────────
if __name__ == "__main__":
    print("正在测试 IEEE Xplore 搜索...\n")
    results = search_papers("transformer radar target detection", max_results=3)

    if results and "error" in results[0]:
        print(f"状态: {results[0]['error']}")
    else:
        print(f"找到 {len(results)} 篇论文：\n")
        for i, p in enumerate(results, 1):
            print(format_paper_brief(p, index=i))
