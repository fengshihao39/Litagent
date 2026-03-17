"""
Litagent - 历史记录服务层

负责会话 CRUD、搜索记录存取、收藏管理。
所有数据库操作都在这里，API 层不直接碰 SQL。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from litagent.backend.app.core.storage import get_connection
from litagent.backend.app.models.history import (
    FavoriteItem,
    SearchRecord,
    SessionDetail,
    SessionInfo,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── 会话管理 ────────────────────────────────────────────────────────────────


def create_session(title: str = "新对话") -> SessionInfo:
    """新建一个搜索会话。"""
    sid = str(uuid.uuid4())
    now = _now_iso()
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (sid, title, now, now),
        )
    conn.close()
    return SessionInfo(id=sid, title=title, created_at=now, updated_at=now)


def list_sessions(limit: int = 50) -> list[SessionInfo]:
    """列出所有会话，最新的在前。"""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.created_at, s.updated_at,
               COALESCE(r.query, '')       AS last_query,
               COALESCE(r.result_count, 0) AS result_count
        FROM sessions s
        LEFT JOIN (
            SELECT session_id,
                   query,
                   JSON_ARRAY_LENGTH(results_json) AS result_count
            FROM search_records
            WHERE id IN (
                SELECT id FROM search_records sr2
                WHERE sr2.session_id = search_records.session_id
                ORDER BY created_at DESC LIMIT 1
            )
        ) r ON r.session_id = s.id
        ORDER BY s.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [
        SessionInfo(
            id=row["id"],
            title=row["title"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_query=row["last_query"] or "",
            result_count=row["result_count"] or 0,
        )
        for row in rows
    ]


def get_session_detail(session_id: str) -> SessionDetail | None:
    """获取某个会话及其所有搜索记录。"""
    conn = get_connection()
    sess_row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not sess_row:
        conn.close()
        return None

    record_rows = conn.execute(
        "SELECT * FROM search_records WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,),
    ).fetchall()
    conn.close()

    session = SessionInfo(
        id=sess_row["id"],
        title=sess_row["title"],
        created_at=sess_row["created_at"],
        updated_at=sess_row["updated_at"],
    )
    records = [
        SearchRecord(
            id=r["id"],
            session_id=r["session_id"],
            query=r["query"],
            results_json=r["results_json"],
            created_at=r["created_at"],
        )
        for r in record_rows
    ]
    return SessionDetail(session=session, records=records)


def rename_session(session_id: str, new_title: str) -> bool:
    """重命名会话标题。"""
    now = _now_iso()
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "UPDATE sessions SET title=?, updated_at=? WHERE id=?",
            (new_title, now, session_id),
        )
    conn.close()
    return cur.rowcount > 0


def delete_session(session_id: str) -> bool:
    """删除会话（级联删除其下所有搜索记录）。"""
    conn = get_connection()
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.close()
    return cur.rowcount > 0


# ─── 搜索记录 ────────────────────────────────────────────────────────────────


def save_search_record(
    session_id: str,
    query: str,
    results: list[dict],
) -> SearchRecord:
    """保存一次搜索结果快照，同时更新会话的 updated_at。"""
    rid = str(uuid.uuid4())
    now = _now_iso()
    results_json = json.dumps(results, ensure_ascii=False)
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO search_records(id, session_id, query, results_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (rid, session_id, query, results_json, now),
        )
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (now, session_id),
        )
    conn.close()
    return SearchRecord(
        id=rid,
        session_id=session_id,
        query=query,
        results_json=results_json,
        created_at=now,
    )


def get_search_record(record_id: str) -> SearchRecord | None:
    """按记录 id 获取单条搜索记录。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM search_records WHERE id=?", (record_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    return SearchRecord(
        id=row["id"],
        session_id=row["session_id"],
        query=row["query"],
        results_json=row["results_json"],
        created_at=row["created_at"],
    )


# ─── 收藏管理 ────────────────────────────────────────────────────────────────


def toggle_favorite(paper_key: str, paper_json: str) -> dict:
    """收藏/取消收藏。返回 {'action': 'added'|'removed', 'paper_key': ...}。"""
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM favorites WHERE paper_key=?", (paper_key,)
    ).fetchone()

    if existing:
        with conn:
            conn.execute("DELETE FROM favorites WHERE paper_key=?", (paper_key,))
        conn.close()
        return {"action": "removed", "paper_key": paper_key}
    else:
        fid = str(uuid.uuid4())
        now = _now_iso()
        with conn:
            conn.execute(
                "INSERT INTO favorites(id, paper_key, paper_json, created_at) VALUES (?,?,?,?)",
                (fid, paper_key, paper_json, now),
            )
        conn.close()
        return {"action": "added", "paper_key": paper_key}


def list_favorites() -> list[FavoriteItem]:
    """列出所有收藏，最新的在前。"""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM favorites ORDER BY created_at DESC").fetchall()
    conn.close()
    return [
        FavoriteItem(
            id=row["id"],
            paper_key=row["paper_key"],
            paper_json=row["paper_json"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def is_favorite(paper_key: str) -> bool:
    """检查某篇论文是否已收藏。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM favorites WHERE paper_key=?", (paper_key,)
    ).fetchone()
    conn.close()
    return row is not None
