"""
Litagent - FastAPI 后端搜索接口
"""

from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from Litagent.backend.app.models.response import SearchResponse
from Litagent.backend.app.services.search_service import search_papers_service

router = APIRouter()


@router.post("/search", response_model=SearchResponse)
async def search(
    query: str = Form(default=""),
    file: Optional[UploadFile] = File(default=None),
    year_from: Optional[int] = Form(default=None),
    max_results: int = Form(default=10),
    use_domain_vocab: bool = Form(default=True),
    use_arxiv_categories: bool = Form(default=True),
) -> SearchResponse:
    """向后端发送搜索请求。

    Args:
        query (str, optional): 搜索关键词. Defaults to Form(default="").
        file (Optional[UploadFile], optional): 用户上传的文献文件. Defaults to File(default=None).
        year_from (Optional[int], optional): 返回文献年份的最早值. Defaults to Form(default=None).
        max_results (int, optional): 返回文献的最大数量. Defaults to Form(default=10).
        use_domain_vocab (bool, optional): 是否开启领域词汇替换. Defaults to Form(default=True).
        use_arxiv_categories (bool, optional): 是否使用 arXiv 分类. Defaults to Form(default=True).

    Returns:
        SearchResponse: 搜索响应。
    """
    return await search_papers_service(
        query=query,
        file=file,
        year_from=year_from,
        max_results=max_results,
        use_domain_vocab=use_domain_vocab,
        use_arxiv_categories=use_arxiv_categories,
    )
