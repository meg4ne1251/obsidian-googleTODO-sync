"""DB初期化と排他制御の単体テスト。"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, locks  # noqa: E402


class DbInitTest(unittest.TestCase):
    def test_initialize_creates_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subdir" / "state.sqlite"
            db.initialize(path)
            with sqlite3.connect(path) as conn:
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
        self.assertEqual(
            {"sync_state", "archived_tasks", "process_locks"} & tables,
            {"sync_state", "archived_tasks", "process_locks"},
        )

    def test_archived_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.sqlite"
            conn = db.connect(path)
            db.add_archived(conn, "abc", "仕事")
            db.add_archived(conn, "def", "個人")
            self.assertEqual(db.list_archived_ids(conn), {"abc", "def"})
            row = db.get_archived(conn, "abc")
            self.assertIsNotNone(row)
            self.assertEqual(row["list_name"], "仕事")
            db.remove_archived(conn, "abc")
            self.assertEqual(db.list_archived_ids(conn), {"def"})

    def test_sync_state_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(Path(tmp) / "s.sqlite")
            db.upsert_sync_state(conn, "todo-仕事.md", last_obsidian_mtime="100")
            row = db.get_sync_state(conn, "todo-仕事.md")
            self.assertEqual(row["last_obsidian_mtime"], "100")
            db.upsert_sync_state(conn, "todo-仕事.md", last_script_written_at="2025-01-01T00:00:00")
            row = db.get_sync_state(conn, "todo-仕事.md")
            self.assertEqual(row["last_obsidian_mtime"], "100")  # 維持
            self.assertEqual(row["last_script_written_at"], "2025-01-01T00:00:00")


class LocksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "lk.sqlite")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_basic_acquire_release(self) -> None:
        pid = locks.acquire(self.conn, "x", pid=12345, max_retry=0)
        self.assertEqual(pid, 12345)
        # 別の pid では取得できない
        with self.assertRaises(locks.LockAcquireError):
            locks.acquire(self.conn, "x", pid=99999, max_retry=0, sleep_func=lambda s: None)
        locks.release(self.conn, "x", pid=12345)
        # release 後は取得可能
        locks.acquire(self.conn, "x", pid=99999, max_retry=0)

    def test_context_manager_releases_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with locks.lock(self.conn, "x", pid=42, max_retry=0):
                raise RuntimeError("boom")
        cur = self.conn.execute("SELECT COUNT(*) FROM process_locks").fetchone()
        self.assertEqual(cur[0], 0)

    def test_stale_lock_is_recovered(self) -> None:
        # 偽のスタールロックを直接 INSERT（古い時刻、存在しない pid）
        old_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.conn.execute(
            "INSERT INTO process_locks(lock_name, pid, acquired_at) VALUES (?, ?, ?)",
            ("livesync_vault", 999_999, old_time),
        )
        # スタールロックを除去して取得できる
        pid = locks.acquire(
            self.conn,
            "livesync_vault",
            pid=os.getpid(),
            timeout_sec=600,
            max_retry=0,
            sleep_func=lambda s: None,
        )
        self.assertEqual(pid, os.getpid())

    def test_active_lock_blocks(self) -> None:
        # 自身の pid（生きている）でロックを保持
        my = os.getpid()
        locks.acquire(self.conn, "y", pid=my, max_retry=0)
        # 別の pid から取得試行 → リトライ上限で失敗
        sleeps = []
        with self.assertRaises(locks.LockAcquireError):
            locks.acquire(
                self.conn,
                "y",
                pid=my + 1,
                max_retry=2,
                retry_interval_sec=0,
                sleep_func=lambda s: sleeps.append(s),
            )
        # max_retry=2 → 初回+2回リトライ で計3回失敗。sleep は2回挟まれる
        self.assertEqual(len(sleeps), 2)
        locks.release(self.conn, "y", pid=my)


if __name__ == "__main__":
    unittest.main()
