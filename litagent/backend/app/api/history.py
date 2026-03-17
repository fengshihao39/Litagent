"""
Litagent - 历史记录 API 路由
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from litagent.backend.app.models.history import (
    FavoriteItem,
    FavoriteToggleRequest,
    SearchRecordCreate,
    SessionCreate,
    SessionDetail,
    SessionInfo,
)
from litagent.backend.app.services.history_service import (
    create_session,
    delete_session,
    get_session_detail,
    get_search_record,
    is_favorite,
    list_favorites,
    list_sessions,
    rename_session,
    save_search_record,
    toggle_favorite,
)

router = APIRouter(prefix="/history", tags=["history"])


# ─── 会话管理 ────────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=SessionInfo)
def api_create_session(body: SessionCreate) -> SessionInfo:
    """新建会话。"""
    return create_session(title=body.title)


@router.get("/sessions", response_model=list[SessionInfo])
def api_list_sessions(limit: int = 50) -> list[SessionInfo]:
    """获取历史会话列表（最新在前）。"""
    return list_sessions(limit=limit)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def api_get_session(session_id: str) -> SessionDetail:
    """获取会话详情及其所有搜索记录。"""
    detail = get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="会话不存在")
    return detail


@router.patch("/sessions/{session_id}/title")
def api_rename_session(session_id: str, body: SessionCreate) -> dict:
    """重命名会话。"""
    ok = rename_session(session_id, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
def api_delete_session(session_id: str) -> dict:
    """删除会话及其所有搜索记录。"""
    ok = delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


# ─── 搜索记录 ────────────────────────────────────────────────────────────────


@router.post("/search-records")
def api_save_search_record(body: SearchRecordCreate) -> dict:
    """保存一次搜索记录（由前端在搜索完成后调用）。"""
    try:
        results = json.loads(body.results_json)
    except (ValueError, TypeError):
        results = []
    record = save_search_record(
        session_id=body.session_id,
        query=body.query,
        results=results,
    )
    return {"ok": True, "record_id": record.id}


@router.get("/search-records/{record_id}")
def api_get_search_record(record_id: str) -> dict:
    """获取某条搜索记录。"""
    record = get_search_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="搜索记录不存在")
    return record.model_dump()


# ─── 收藏 ────────────────────────────────────────────────────────────────────


@router.post("/favorites/toggle")
def api_toggle_favorite(body: FavoriteToggleRequest) -> dict:
    """收藏 / 取消收藏某篇论文。"""
    return toggle_favorite(
        paper_key=body.paper_key,
        paper_json=body.paper_json,
    )


@router.get("/favorites", response_model=list[FavoriteItem])
def api_list_favorites() -> list[FavoriteItem]:
    """获取收藏列表。"""
    return list_favorites()


@router.get("/favorites/check/{paper_key}")
def api_check_favorite(paper_key: str) -> dict:
    """检查某篇论文是否已收藏。"""
    return {"is_favorite": is_favorite(paper_key)}
