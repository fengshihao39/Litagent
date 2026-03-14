"""
Litagent - 搜索响应模型
"""

from typing import List, Optional

from pydantic import BaseModel


class PaperResult(BaseModel):
    """文献模型。"""
    title: str
    abstract: str
    authors: List[str]
    year: Optional[int]
    keywords: List[str]
    venue: str
    doi: str
    source: str
    abs_url: str
    citation_count: int
    tldr: str


class SearchResponse(BaseModel):
    """搜索相应模型。"""
    results: List[PaperResult]
    translated_query: str
    total: int
