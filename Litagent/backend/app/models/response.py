"""
Litagent - 搜索响应模型
"""

from pydantic import BaseModel


class PaperResult(BaseModel):
    """文献模型。"""

    title: str
    abstract: str
    authors: list[str]
    year: int | None
    keywords: list[str]
    venue: str
    doi: str
    source: str
    abs_url: str
    citation_count: int
    tldr: str


class SearchResponse(BaseModel):
    """搜索相应模型。"""

    results: list[PaperResult]
    total: int
