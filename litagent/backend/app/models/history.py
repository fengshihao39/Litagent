"""
Litagent - 历史记录 Pydantic 模型
"""

from __future__ import annotations

from pydantic import BaseModel


class SessionCreate(BaseModel):
    """创建新会话的请求体。"""

    title: str = "新对话"


class SessionInfo(BaseModel):
    """会话摘要信息。"""

    id: str
    title: str
    created_at: str
    updated_at: str
    last_query: str = ""  # 该会话最后一次搜索词，方便侧栏展示
    result_count: int = 0  # 该会话累计搜索到的文献数


class SearchRecordCreate(BaseModel):
    """保存一条搜索记录的请求体。"""

    session_id: str
    query: str
    results_json: str  # JSON 字符串，即序列化后的 List[PaperResult]


class SearchRecord(BaseModel):
    """搜索记录详情。"""

    id: str
    session_id: str
    query: str
    results_json: str
    created_at: str


class SessionDetail(BaseModel):
    """会话详情（含所有搜索记录）。"""

    session: SessionInfo
    records: list[SearchRecord]


class FavoriteToggleRequest(BaseModel):
    """收藏/取消收藏请求体。"""

    paper_key: str  # 唯一标识，优先用 DOI，其次 abs_url，最后 title[:60]
    paper_json: str  # 序列化的 PaperResult JSON


class FavoriteItem(BaseModel):
    """收藏条目。"""

    id: str
    paper_key: str
    paper_json: str
    created_at: str
