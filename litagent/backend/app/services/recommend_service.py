"""
Litagent - 相似论文推荐服务（第一版：轻量关键词/标题相似）

不使用 embedding，基于关键词重叠 + 标题词重叠打分，
从已有的搜索结果池中挑出最相似的论文。
后续升级为 embedding 时只需替换 _similarity_score 实现。
"""

from __future__ import annotations

import re


def _tokenize(text: str) -> set[str]:
    """简单分词：小写、提取 4+ 字母单词。"""
    return set(re.findall(r"[a-zA-Z]{4,}", text.lower()))


def _similarity_score(paper_a: dict, paper_b: dict) -> float:
    """
    基于关键词 + 标题词 Jaccard 相似度打分 [0, 1]。

    - 关键词权重 60%
    - 标题词重叠 40%
    """
    kw_a = set(k.lower() for k in paper_a.get("keywords", []))
    kw_b = set(k.lower() for k in paper_b.get("keywords", []))

    title_a = _tokenize(paper_a.get("title", ""))
    title_b = _tokenize(paper_b.get("title", ""))

    def jaccard(s1: set, s2: set) -> float:
        if not s1 and not s2:
            return 0.0
        union = s1 | s2
        if not union:
            return 0.0
        return len(s1 & s2) / len(union)

    kw_sim = jaccard(kw_a, kw_b)
    title_sim = jaccard(title_a, title_b)

    return round(0.60 * kw_sim + 0.40 * title_sim, 4)


def _paper_key(paper: dict) -> str:
    """生成论文去重 key。"""
    doi = (paper.get("doi") or "").strip()
    if doi:
        return doi
    url = (paper.get("abs_url") or "").strip()
    if url:
        return url
    return (paper.get("title") or "")[:60].lower().strip()


def find_related_papers(
    target: dict,
    candidates: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """
    从 candidates 中找出与 target 最相似的 top_k 篇论文。

    Args:
        target: 当前论文（字典格式）
        candidates: 搜索结果池
        top_k: 返回数量

    Returns:
        按相似度降序排列的推荐列表（已附 similarity_score 字段）
    """
    target_key = _paper_key(target)
    scored: list[tuple[float, dict]] = []

    for paper in candidates:
        if _paper_key(paper) == target_key:
            continue
        score = _similarity_score(target, paper)
        if score > 0:
            p = dict(paper)
            p["similarity_score"] = score
            scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:top_k]]
