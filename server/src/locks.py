"""排他制御 (process_locks テーブル) ライブラリ。"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


class LockAcquireError(RuntimeError):
    """ロック取得に失敗した場合に送出される。"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_acquired_at(value: str) -> datetime:
    # 保存時に utcnow().isoformat() を使うので、tz が無い場合は UTC とみなす
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _pid_alive(pid: int) -> bool:
    """pid が生きているかを確認する (POSIX)。自プロセスは常に True。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # シグナル送信権限がないだけでプロセスは存在
        return True
    except OSError:
        return False
    return True


def _try_insert(conn: sqlite3.Connection, lock_name: str, pid: int) -> bool:
    try:
        conn.execute(
            "INSERT INTO process_locks(lock_name, pid, acquired_at) VALUES (?, ?, ?)",
            (lock_name, pid, _utcnow().isoformat()),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def _existing_lock(conn: sqlite3.Connection, lock_name: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM process_locks WHERE lock_name = ?", (lock_name,))
    return cur.fetchone()


def acquire(
    conn: sqlite3.Connection,
    lock_name: str,
    *,
    timeout_sec: int = 600,
    retry_interval_sec: int = 10,
    max_retry: int = 6,
    pid: Optional[int] = None,
    sleep_func=time.sleep,
    now_func=_utcnow,
) -> int:
    """ロックを取得する。失敗時は LockAcquireError を送出。
    取得成功時に DB に書き込んだ pid を返す。
    """
    actual_pid = pid if pid is not None else os.getpid()
    attempts = 0
    while True:
        if _try_insert(conn, lock_name, actual_pid):
            logger.debug("Lock acquired: %s by pid=%d", lock_name, actual_pid)
            return actual_pid
        # 競合発生
        existing = _existing_lock(conn, lock_name)
        if existing is None:
            # レース：再試行
            continue
        acquired_at = _parse_acquired_at(existing["acquired_at"])
        age = now_func() - acquired_at
        if age >= timedelta(seconds=timeout_sec) and not _pid_alive(int(existing["pid"])):
            # スタールロックとみなし解除
            logger.warning(
                "Stale lock detected (lock=%s pid=%s age=%ss). Forcibly releasing.",
                lock_name, existing["pid"], int(age.total_seconds()),
            )
            conn.execute(
                "DELETE FROM process_locks WHERE lock_name = ? AND pid = ?",
                (lock_name, existing["pid"]),
            )
            continue
        attempts += 1
        if attempts > max_retry:
            raise LockAcquireError(
                f"Failed to acquire lock '{lock_name}' after {max_retry} retries"
            )
        sleep_func(retry_interval_sec)


def release(conn: sqlite3.Connection, lock_name: str, pid: Optional[int] = None) -> None:
    """指定された pid のロックを解放する。"""
    actual_pid = pid if pid is not None else os.getpid()
    conn.execute(
        "DELETE FROM process_locks WHERE lock_name = ? AND pid = ?",
        (lock_name, actual_pid),
    )


@contextmanager
def lock(
    conn: sqlite3.Connection,
    lock_name: str,
    *,
    timeout_sec: int = 600,
    retry_interval_sec: int = 10,
    max_retry: int = 6,
    pid: Optional[int] = None,
    sleep_func=time.sleep,
) -> Iterator[int]:
    """with 文用ヘルパー。finally で確実に解放する。"""
    acquired_pid = acquire(
        conn,
        lock_name,
        timeout_sec=timeout_sec,
        retry_interval_sec=retry_interval_sec,
        max_retry=max_retry,
        pid=pid,
        sleep_func=sleep_func,
    )
    try:
        yield acquired_pid
    finally:
        release(conn, lock_name, acquired_pid)


# --- ロック名定義 -----------------------------------------------------------

LIVESYNC_VAULT = "livesync_vault"
