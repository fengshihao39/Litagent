"""
Litagent - 搜索请求模型
"""

from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """搜索请求模型。"""
    query: str = Field(default="", description="Search keywords")
    year_from: Optional[int] = Field(default=None, description="Filter from year")
    max_results: int = Field(default=10, description="Max results to return")
    use_domain_vocab: bool = Field(default=True, description="Use domain vocab")
    use_arxiv_categories: bool = Field(default=True, description="Use arXiv categories")
