"""
Semantic Scholar 搜索模块
特点：
  - 免费，无需 API Key
  - 收录 2亿+ 篇论文，覆盖 arXiv + IEEE + ACM + Nature 等
  - 支持语义搜索（不只是关键词匹配）
  - 返回引用数、被引数，可按影响力排序
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import time
from typing import List, Dict, Optional

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"

# 需要返回的字段
FIELDS = ",".join(
    [
        "paperId",
        "externalIds",
        "title",
        "abstract",
        "authors",
        "year",
        "publicationDate",
        "venue",
        "publicationVenue",
        "citationCount",
        "referenceCount",
        "openAccessPdf",
        "fieldsOfStudy",
        "tldr",
    ]
)

# 西电三大方向的语义搜索扩展词
DOMAIN_KEYWORDS = {
    "电子信息": [
        "electronic information",
        "signal processing",
        "communication systems",
    ],
    "人工智能": ["artificial intelligence", "machine learning", "deep learning"],
    "雷达信号处理": [
        "radar signal processing",
        "synthetic aperture radar",
        "target detection",
    ],
}


def search_papers(
    query: str,
    max_results: int = 8,
    fields_of_study: Optional[List[str]] = None,
    min_citations: int = 0,
    sort_by: str = "relevance",  # relevance | citationCount
) -> List[Dict]:
    """
    使用 Semantic Scholar API 搜索论文

    参数:
        query          : 搜索关键词（英文）
        max_results    : 返回数量
        fields_of_study: 领域过滤，如 ["Computer Science", "Electrical Engineering"]
        min_citations  : 最低引用数过滤（用于小方向精准搜索时过滤低质量结果）
        sort_by        : 排序方式

    返回:
        统一格式的论文列表（与 arxiv_search 格式兼容）
    """
    params = {
        "query": query,
        "limit": min(max_results * 2, 50),  # 多取一些，方便后续过滤
        "fields": FIELDS,
    }

    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)

    url = f"{SEMANTIC_SCHOLAR_API}?{urllib.parse.urlencode(params)}"

    headers = {
        # Polite pool：带邮箱有助于降低限流概率
        "User-Agent": "StarfireAgent/1.0 (mailto:xxx@stu.xidian.edu.cn)",
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as response:
            content = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            # 限流：等待后重试
            time.sleep(3)
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=20) as response:
                    content = response.read().decode("utf-8")
            except urllib.error.HTTPError as e2:
                return [
                    {
                        "error": f"Semantic Scholar 限流(429)，请稍后重试: {e2}",
                        "source": "semantic_scholar",
                    }
                ]
            except Exception as e2:
                return [
                    {
                        "error": f"Semantic Scholar 请求失败: {e2}",
                        "source": "semantic_scholar",
                    }
                ]
        else:
            return [
                {
                    "error": f"Semantic Scholar API 错误 {e.code}: {e}",
                    "source": "semantic_scholar",
                }
            ]
    except Exception as e:
        return [
            {
                "error": f"Semantic Scholar 网络请求失败: {e}",
                "source": "semantic_scholar",
            }
        ]

    return _parse_response(content, max_results, min_citations, sort_by)


def _parse_response(
    json_content: str,
    max_results: int,
    min_citations: int,
    sort_by: str,
) -> List[Dict]:
    """解析 Semantic Scholar API 返回的 JSON"""
    try:
        data = json.loads(json_content)
    except json.JSONDecodeError as e:
        return [{"error": f"响应解析失败: {e}", "source": "semantic_scholar"}]

    raw_papers = data.get("data", [])
    if not raw_papers:
        return []

    papers = []
    for p in raw_papers:
        # 跳过没有摘要的论文（质量过滤）
        abstract = p.get("abstract") or ""
        if not abstract.strip():
            continue

        title = p.get("title") or ""
        if not title.strip():
            continue

        # 引用数过滤
        citation_count = p.get("citationCount") or 0
        if citation_count < min_citations:
            continue

        # 作者列表
        authors = [a.get("name", "") for a in p.get("authors", []) if a.get("name")]

        # 发表时间
        pub_date = p.get("publicationDate") or ""
        year = str(p.get("year") or "")
        if pub_date:
            published = pub_date[:10]
        elif year:
            published = f"{year}-01-01"
        else:
            published = "unknown"

        # 期刊/会议
        venue = ""
        pub_venue = p.get("publicationVenue")
        if pub_venue:
            venue = pub_venue.get("name", "") or p.get("venue", "")
        else:
            venue = p.get("venue", "")

        # 外部 ID（arXiv ID 或 DOI）
        external_ids = p.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv", "")
        doi = external_ids.get("DOI", "")
        paper_id = p.get("paperId", "")

        # 链接
        if arxiv_id:
            abs_url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        elif doi:
            abs_url = f"https://doi.org/{doi}"
            pdf_url = ""
        else:
            abs_url = f"https://www.semanticscholar.org/paper/{paper_id}"
            pdf_url = ""

        # 开放获取 PDF
        open_pdf = p.get("openAccessPdf")
        if open_pdf and open_pdf.get("url"):
            pdf_url = open_pdf["url"]

        # TLDR（Semantic Scholar 自动生成的一句话总结）
        tldr = ""
        tldr_obj = p.get("tldr")
        if tldr_obj and tldr_obj.get("text"):
            tldr = tldr_obj["text"]

        # 研究领域
        fields = p.get("fieldsOfStudy") or []

        papers.append(
            {
                "source": "semantic_scholar",
                "paper_id": paper_id,
                "arxiv_id": arxiv_id,
                "doi": doi,
                "title": title,
                "authors": authors,
                "published": published,
                "year": year,
                "venue": venue,
                "categories": fields,
                "summary": abstract,
                "tldr": tldr,
                "citation_count": citation_count,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )

    # 排序
    if sort_by == "citationCount":
        papers.sort(key=lambda x: x.get("citation_count", 0), reverse=True)

    return papers[:max_results]


def format_paper_brief(paper: Dict, index: Optional[int] = None) -> str:
    """格式化单篇论文为可读字符串"""
    if "error" in paper:
        return f"[错误] {paper['error']}"

    prefix = f"[{index}] " if index is not None else ""
    authors_str = ", ".join(paper["authors"][:3])
    if len(paper["authors"]) > 3:
        authors_str += " 等"

    venue_str = f"  |  发表于: {paper['venue']}" if paper.get("venue") else ""
    citation_str = (
        f"  |  被引: {paper['citation_count']}次" if paper.get("citation_count") else ""
    )
    tldr_str = f"\n   一句话: {paper['tldr']}" if paper.get("tldr") else ""

    return (
        f"{prefix}**{paper['title']}**\n"
        f"   作者: {authors_str}\n"
        f"   时间: {paper['published']}{venue_str}{citation_str}\n"
        f"   来源: Semantic Scholar  |  链接: {paper['abs_url']}"
        f"{tldr_str}\n"
        f"   摘要: {paper['summary'][:200]}...\n"
    )


# ── 简单测试 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("正在测试 Semantic Scholar 搜索...\n")

    # 测试小方向精准搜索
    results = search_papers(
        query="few-shot radar modulation recognition",
        max_results=4,
        min_citations=0,
    )

    if results and "error" in results[0]:
        print(f"错误: {results[0]['error']}")
    else:
        print(f"找到 {len(results)} 篇论文：\n")
        for i, p in enumerate(results, 1):
            print(format_paper_brief(p, index=i))
