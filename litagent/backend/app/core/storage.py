"""
Litagent - SQLite 本地存储层

负责初始化数据库、提供连接，以及创建所有表结构。
数据库文件默认放在项目根目录的 litagent.db。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from litagent.backend.app.core.config import ROOT_DIR

DB_PATH = ROOT_DIR / "litagent.db"


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 连接，启用 WAL 模式和行工厂。"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """初始化数据库，创建所有表（如果不存在）。"""
    conn = get_connection()
    with conn:
        # 搜索会话表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                title       TEXT NOT NULL DEFAULT '新对话',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            )
        """)

        # 每次搜索记录表（一个 session 可有多次搜索）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_records (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                query       TEXT NOT NULL,
                results_json TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT NOT NULL
            )
        """)

        # 收藏表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id          TEXT PRIMARY KEY,
                paper_key   TEXT NOT NULL UNIQUE,
                paper_json  TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """)

        # 索引
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_records_session "
            "ON search_records(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_favorites_key ON favorites(paper_key)"
        )
    conn.close()
