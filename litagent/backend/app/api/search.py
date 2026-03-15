"""
Litagent - FastAPI 后端搜索接口
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from litagent.backend.app.models.response import SearchResponse
from litagent.backend.app.services.search_service import search_papers_service

router = APIRouter()


@router.post("/search")
async def search(
    query: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
    year_from: Annotated[int | None, Form()] = None,
    max_results: Annotated[int, Form()] = 10,
    use_arxiv_categories: Annotated[bool, Form()] = True,
) -> SearchResponse:
    """向后端发送搜索请求。

    Args:
        query (Annotated[str, Form, optional): 搜索关键词。
        file (Annotated[UploadFile  |  None, File, optional): 用户上传的文献文件。
        year_from (Annotated[int  |  None, Form, optional): 返回文献年份的最早值。
        max_results (Annotated[int, Form, optional): 返回文献的最大数量。
        use_arxiv_categories (Annotated[bool, Form, optional): 是否使用 arXiv 分类。

    Returns:
        SearchResponse: 搜索响应。
    """

    return await search_papers_service(
        query=query,
        file=file,
        year_from=year_from,
        max_results=max_results,
        use_arxiv_categories=use_arxiv_categories,
    )
