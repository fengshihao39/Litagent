"""
Litagent - 论文详情聚合服务

把一篇论文的基础字段 + 热度分 + 收藏状态 + 中文标题组合成完整的详情对象。
"""

from __future__ import annotations

from litagent.backend.app.services.history_service import is_favorite
from litagent.backend.app.services.metrics_service import (
    compute_heat_label,
    compute_heat_score,
)


def build_paper_detail(paper: dict) -> dict:
    """
    在原始 paper 字典基础上附加扩展字段，返回详情视图所需的完整数据。

    附加字段：
      - heat_score       浮点热度分 [0, 1]
      - heat_label       热度标签（高/中/普通/冷门）
      - is_favorite      是否已收藏
      - paper_key        唯一标识（供收藏、收藏检查使用）
      - title_zh         中文标题（先留空，由前端按需单独调用 /paper/translate 获取）
    """
    citation_count = paper.get("citation_count") or 0
    year = paper.get("year")
    source = paper.get("source", "")

    heat_score = compute_heat_score(citation_count, year, source)
    heat_label = compute_heat_label(heat_score)
    paper_key = _make_paper_key(paper)

    return {
        **paper,
        "heat_score": heat_score,
        "heat_label": heat_label,
        "is_favorite": is_favorite(paper_key),
        "paper_key": paper_key,
        "title_zh": "",  # 由前端单独请求翻译
    }


def _make_paper_key(paper: dict) -> str:
    """生成论文唯一标识，优先 DOI > abs_url > 标题截断。"""
    doi = (paper.get("doi") or "").strip()
    if doi:
        return doi
    url = (paper.get("abs_url") or "").strip()
    if url:
        return url
    return (paper.get("title") or "")[:60].lower().strip()
