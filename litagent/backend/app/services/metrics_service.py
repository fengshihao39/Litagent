"""
Litagent - 论文指标计算服务

计算热度分（heat_score），综合引用数、年份新近度、来源权重。
不依赖外部数据，完全用现有字段本地计算。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def _recency_score(year: int | None) -> float:
    """年份新近度分，越新越高，满分 1.0。"""
    if not year:
        return 0.3
    current_year = datetime.now(timezone.utc).year
    age = max(current_year - year, 0)
    # 5 年内接近满分，超过 15 年趋近 0
    return max(0.0, 1.0 - age / 15.0)


def _citation_score(citation_count: int) -> float:
    """引用数分，用对数归一化，满分 1.0。"""
    if citation_count <= 0:
        return 0.0
    # log(1001) ≈ 6.9，以此作为上限参考
    return min(1.0, math.log(citation_count + 1) / math.log(1001))


def _source_weight(source: str) -> float:
    """数据源可信度权重。"""
    weights = {
        "semantic_scholar": 1.0,
        "ieee": 1.0,
        "crossref": 0.9,
        "arxiv": 0.8,
        "upload": 0.5,
    }
    return weights.get(source, 0.7)


def compute_heat_score(
    citation_count: int,
    year: int | None,
    source: str = "",
) -> float:
    """
    综合热度分 [0.0, 1.0]。

    权重：
      - 引用数    60%
      - 年份新近度 25%
      - 来源可信度 15%
    """
    cs = _citation_score(citation_count)
    rs = _recency_score(year)
    sw = _source_weight(source)
    score = 0.60 * cs + 0.25 * rs + 0.15 * sw
    return round(min(score, 1.0), 4)


def compute_heat_label(heat_score: float) -> str:
    """把热度分映射成可读标签。"""
    if heat_score >= 0.75:
        return "高热度"
    if heat_score >= 0.45:
        return "中热度"
    if heat_score >= 0.20:
        return "普通"
    return "较冷门"
