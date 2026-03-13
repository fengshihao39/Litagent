"""
多源并联搜索入口
同时调用 arXiv + Semantic Scholar + IEEE Xplore + Crossref
合并去重，按相关性排序后统一返回
"""

import threading
from typing import Dict, List, Optional

from Litagent.services.search.arxiv import search_papers as arxiv_search
from Litagent.services.search.crossref import search_papers as crossref_search
from Litagent.services.search.ieee import search_papers as ieee_search
from Litagent.services.search.semantic_scholar import (
    search_papers as semantic_search,
)


def multi_search(
    query: str,
    max_results: int = 10,
    sources: Optional[List[str]] = None,
    year_from: Optional[int] = None,
    use_arxiv_categories: bool = True,
) -> List[Dict]:
    """
    四源并联搜索

    参数:
        query       : 搜索关键词（英文）
        max_results : 最终返回总数
        sources     : 指定来源，默认全部。可选 ["arxiv", "semantic_scholar", "ieee", "crossref"]
        year_from   : 最早发表年份（如 2020 表示只返回 2020 年及以后的论文）
        use_arxiv_categories: 是否启用 arXiv 默认分类过滤

    返回:
        去重合并后的论文列表，每篇带 source 标识
    """
    if sources is None:
        sources = ["arxiv", "semantic_scholar", "ieee", "crossref"]

    # 每个源各取一定数量，合并后保证总数充足
    per_source = max(max_results, 8)

    results: Dict[str, List[Dict]] = {}
    errors: Dict[str, str] = {}
    lock = threading.Lock()

    def run_arxiv():
        try:
            papers = arxiv_search(
                query,
                max_results=per_source,
                use_default_categories=use_arxiv_categories,
            )
            for p in papers:
                if "error" not in p:
                    p.setdefault("source", "arxiv")
            with lock:
                results["arxiv"] = papers
        except Exception as e:
            with lock:
                errors["arxiv"] = str(e)

    def run_semantic():
        try:
            papers = semantic_search(query, max_results=per_source)
            with lock:
                results["semantic_scholar"] = papers
        except Exception as e:
            with lock:
                errors["semantic_scholar"] = str(e)

    def run_ieee():
        try:
            papers = ieee_search(query, max_results=per_source, start_year=year_from)
            with lock:
                results["ieee"] = papers
        except Exception as e:
            with lock:
                errors["ieee"] = str(e)

    def run_crossref():
        try:
            papers = crossref_search(query, max_results=per_source, min_year=year_from)
            with lock:
                results["crossref"] = papers
        except Exception as e:
            with lock:
                errors["crossref"] = str(e)

    # 并发启动搜索线程
    threads = []
    if "arxiv" in sources:
        threads.append(threading.Thread(target=run_arxiv))
    if "semantic_scholar" in sources:
        threads.append(threading.Thread(target=run_semantic))
    if "ieee" in sources:
        threads.append(threading.Thread(target=run_ieee))
    if "crossref" in sources:
        threads.append(threading.Thread(target=run_crossref))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=25)  # 最多等 25 秒

    # 合并所有结果：S2 > arXiv > Crossref > IEEE（按相关性质量排序）
    all_papers: List[Dict] = []
    for source in ["semantic_scholar", "arxiv", "crossref", "ieee"]:
        source_papers = results.get(source, [])
        for p in source_papers:
            if "error" not in p:
                all_papers.append(p)

    # 去重：优先用 arXiv ID，其次用 DOI，最后用标题
    seen_titles: set = set()
    seen_arxiv_ids: set = set()
    seen_dois: set = set()
    deduped: List[Dict] = []

    for p in all_papers:
        arxiv_id = p.get("arxiv_id", "")
        doi = p.get("doi", "")
        title_key = _normalize_title(p.get("title", ""))

        if arxiv_id and arxiv_id in seen_arxiv_ids:
            continue
        if doi and doi in seen_dois:
            continue
        if title_key and title_key in seen_titles:
            continue

        if arxiv_id:
            seen_arxiv_ids.add(arxiv_id)
        if doi:
            seen_dois.add(doi)
        if title_key:
            seen_titles.add(title_key)

        deduped.append(p)

    # 年份过滤（对不原生支持年份过滤的来源做后处理）
    if year_from is not None:
        filtered_by_year = []
        for p in deduped:
            py = _get_year(p)
            if py is None or py >= year_from:
                filtered_by_year.append(p)
        deduped = filtered_by_year

    # 截取最终数量：各源均衡混合，避免某一源独占全部结果
    # 先按来源分组，轮流取，确保多样性
    buckets: Dict[str, List[Dict]] = {}
    for p in deduped:
        src = p.get("source", "unknown")
        buckets.setdefault(src, []).append(p)

    final: List[Dict] = []
    source_order = ["semantic_scholar", "arxiv", "crossref", "ieee"]
    while len(final) < max_results:
        added = False
        for src in source_order:
            if len(final) >= max_results:
                break
            if buckets.get(src):
                final.append(buckets[src].pop(0))
                added = True
        if not added:
            break

    return final


def _normalize_title(title: str) -> str:
    """标题标准化，用于去重比较"""
    return title.lower().strip().replace(" ", "").replace("-", "")[:60]


def _get_year(paper: Dict) -> Optional[int]:
    """从论文 dict 中提取发表年份整数，无法获取返回 None"""
    year = paper.get("year")
    if isinstance(year, int):
        return year
    published = paper.get("published", "") or ""
    if published:
        import re

        m = re.search(r"(20\d{2}|19\d{2})", str(published))
        if m:
            return int(m.group(1))
    return None


def format_papers_list(papers: List[Dict]) -> str:
    """格式化多源搜索结果列表"""
    if not papers:
        return "未找到相关论文，请尝试更换关键词。"

    # 来源统计
    source_count: Dict[str, int] = {}
    for p in papers:
        src = p.get("source", "unknown")
        source_count[src] = source_count.get(src, 0) + 1

    source_summary = "  |  ".join(
        [f"{_source_label(s)}: {n}篇" for s, n in source_count.items()]
    )

    lines = [f"共找到 **{len(papers)}** 篇相关论文（{source_summary}）：\n"]

    for i, paper in enumerate(papers, 1):
        lines.append(_format_single(paper, i))
        lines.append("")

    return "\n".join(lines)


def _format_single(paper: Dict, index: int) -> str:
    """格式化单篇论文"""
    source = paper.get("source", "unknown")
    source_badge = _source_label(source)

    authors = paper.get("authors", [])
    authors_str = ", ".join(authors[:3])
    if len(authors) > 3:
        authors_str += " 等"

    venue = paper.get("venue", "")
    venue_str = f"  |  {venue}" if venue else ""

    citation = paper.get("citation_count", 0)
    citation_str = f"  |  被引 {citation} 次" if citation else ""

    tldr = paper.get("tldr", "")
    tldr_str = f"\n   💡 {tldr}" if tldr else ""

    abs_url = paper.get("abs_url", "")

    return (
        f"[{index}] [{source_badge}] **{paper.get('title', 'N/A')}**\n"
        f"   作者: {authors_str}\n"
        f"   时间: {paper.get('published', 'N/A')}{venue_str}{citation_str}\n"
        f"   链接: {abs_url}"
        f"{tldr_str}\n"
        f"   摘要: {paper.get('summary', '')[:200]}...\n"
    )


def _source_label(source: str) -> str:
    labels = {
        "arxiv": "arXiv",
        "semantic_scholar": "S2",
        "ieee": "IEEE",
        "crossref": "Crossref",
    }
    return labels.get(source, source.upper())


# ── 测试 ─────────────────────────────────────────────────
if __name__ == "__main__":
    import datetime

    print("=== 测试多源并联搜索（含年份过滤）===\n")
    query = "few-shot radar modulation recognition"
    year_from = datetime.datetime.now().year - 5  # 近5年

    print(f"查询：{query}")
    print(f"年份过滤：>= {year_from}\n")

    papers = multi_search(query, max_results=8, year_from=year_from)
    print(format_papers_list(papers))
