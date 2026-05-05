"""SQLite アクセスヘルパー。スキーマ初期化と汎用クエリ。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sync_state (
    key                     TEXT PRIMARY KEY,
    last_obsidian_mtime     TEXT,
    last_google_updated     TEXT,
    last_script_written_at  TEXT
);

CREATE TABLE IF NOT EXISTS archived_tasks (
    gtasks_id   TEXT PRIMARY KEY,
    list_name   TEXT NOT NULL,
    archived_at DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS process_locks (
    lock_name   TEXT PRIMARY KEY,
    pid         INTEGER NOT NULL,
    acquired_at DATETIME NOT NULL
);
"""


def initialize(db_path: Path) -> None:
    """DB ファイルとテーブルを生成する。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


def connect(db_path: Path) -> sqlite3.Connection:
    """通常接続を返す（行を sqlite3.Row として取得）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    # 接続時にスキーマがなければ作成（テスト用途で便利）
    conn.executescript(SCHEMA_SQL)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """明示的トランザクション。"""
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    else:
        conn.execute("COMMIT;")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# --- sync_state helpers ----------------------------------------------------


def get_sync_state(conn: sqlite3.Connection, key: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM sync_state WHERE key = ?", (key,))
    return cur.fetchone()


def upsert_sync_state(
    conn: sqlite3.Connection,
    key: str,
    *,
    last_obsidian_mtime: Optional[str] = None,
    last_google_updated: Optional[str] = None,
    last_script_written_at: Optional[str] = None,
) -> None:
    """sync_state を UPSERT。None のカラムは更新しない。"""
    existing = get_sync_state(conn, key)
    if existing is None:
        conn.execute(
            """INSERT INTO sync_state(key, last_obsidian_mtime, last_google_updated, last_script_written_at)
               VALUES (?, ?, ?, ?)""",
            (key, last_obsidian_mtime, last_google_updated, last_script_written_at),
        )
        return
    fields = []
    values: list = []
    if last_obsidian_mtime is not None:
        fields.append("last_obsidian_mtime = ?")
        values.append(last_obsidian_mtime)
    if last_google_updated is not None:
        fields.append("last_google_updated = ?")
        values.append(last_google_updated)
    if last_script_written_at is not None:
        fields.append("last_script_written_at = ?")
        values.append(last_script_written_at)
    if not fields:
        return
    values.append(key)
    conn.execute(f"UPDATE sync_state SET {', '.join(fields)} WHERE key = ?", values)


def mark_script_written(conn: sqlite3.Connection, key: str) -> str:
    """書き込み完了を記録し、保存した時刻を返す。"""
    ts = utcnow_iso()
    upsert_sync_state(conn, key, last_script_written_at=ts)
    return ts


# --- archived_tasks helpers -----------------------------------------------


def add_archived(conn: sqlite3.Connection, gtasks_id: str, list_name: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO archived_tasks(gtasks_id, list_name, archived_at) VALUES (?, ?, ?)",
        (gtasks_id, list_name, utcnow_iso()),
    )


def remove_archived(conn: sqlite3.Connection, gtasks_id: str) -> None:
    conn.execute("DELETE FROM archived_tasks WHERE gtasks_id = ?", (gtasks_id,))


def list_archived_ids(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT gtasks_id FROM archived_tasks")
    return {row["gtasks_id"] for row in cur.fetchall()}


def get_archived(conn: sqlite3.Connection, gtasks_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM archived_tasks WHERE gtasks_id = ?", (gtasks_id,))
    return cur.fetchone()
