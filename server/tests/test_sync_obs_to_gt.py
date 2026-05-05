"""Obsidian → Google Tasks 同期の統合テスト（バックエンドはインメモリ）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, parser, sync_obs_to_gt  # noqa: E402
from src.config import (Config, GoogleConfig, LivesyncConfig, LocksConfig,  # noqa: E402
                        LoggingConfig, PathsConfig, VerifyConfig, ZabbixConfig)
from src.gtasks import InMemoryBackend  # noqa: E402


def make_config(tmp: Path) -> Config:
    vault = tmp / "vault"
    vault.mkdir()
    db_path = tmp / "state.sqlite"
    return Config(
        paths=PathsConfig(vault_dir=vault, db_path=db_path, log_dir=tmp / "log"),
        livesync=LivesyncConfig(npm="npm", cli_dir=".", db_dir=".", timeout_sec=10),
        google=GoogleConfig(credentials_file=tmp / "c.json",
                            token_file=tmp / "t.json", scopes=[]),
        locks=LocksConfig(),
        verify=VerifyConfig(zabbix=ZabbixConfig()),
        logging=LoggingConfig(),
    )


class SyncObsToGtTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cfg = make_config(self.tmp)
        self.backend = InMemoryBackend()
        self.conn = db.connect(self.cfg.paths.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def write_file(self, name: str, content: str) -> Path:
        f = self.cfg.paths.vault_dir / name
        f.write_text(content, encoding="utf-8")
        return f

    def test_create_new_tasks_assigns_ids(self) -> None:
        self.write_file(
            "todo-仕事.md",
            "- [ ] alpha\n  created:: 2025-05-01\n\n- [ ] beta\n  due:: 2025-05-30\n",
        )
        results = sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].created, 2)
        self.assertEqual(results[0].updated, 0)

        # ファイルに gtasks_id が書き戻されている
        re_parsed = parser.parse_file(self.cfg.paths.vault_dir / "todo-仕事.md")
        ids = [t.gtasks_id for t in re_parsed]
        self.assertEqual(len(ids), 2)
        self.assertTrue(all(i and i.startswith("T") for i in ids))

        # Google Tasks 側にも存在する
        tl = next(iter(self.backend.tasklists.values()))
        self.assertEqual(tl.title, "仕事")
        self.assertEqual(len(self.backend.tasks[tl.id]), 2)

    def test_update_existing_task(self) -> None:
        f = self.write_file(
            "todo-仕事.md",
            "- [ ] alpha\n  created:: 2025-05-01\n",
        )
        sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        
        # モックの時計を進めることで、ファイル更新(mtime)や次の同期時間との差を作る
        self.backend.clock += 1000

        # ファイルを編集（タイトル変更）
        re_parsed = parser.parse_file(f)
        re_parsed[0].title = "alpha-updated"
        re_parsed[0].due = "2025-12-31"
        parser.update_file(f, re_parsed)

        # データベースの last_script_written_at を、現在のモック上のタスクの updated 時刻と同じかそれより未来にする。
        # 実際には sync_all 実行時に file_changed があれば記録されるが、
        # モックバックエンドだと一瞬で実行されるため updated 時刻の方が僅かに未来になってしまうことがあるため、
        # ここで明示的にモックタスクの updated を last_script_written_at（過去）より古くしておく
        tl = next(iter(self.backend.tasklists.values()))
        task_id = list(self.backend.tasks[tl.id].keys())[0]
        
        state = db.get_sync_state(self.conn, str(f))
        if state and state["last_script_written_at"]:
            self.backend.tasks[tl.id][task_id]["updated"] = state["last_script_written_at"]

        # 二回目同期
        results = sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].updated, 1)
        self.assertEqual(results[0].created, 0)
        tl = next(iter(self.backend.tasklists.values()))
        task = next(iter(self.backend.tasks[tl.id].values()))
        self.assertEqual(task["title"], "alpha-updated")
        self.assertEqual(task["due"], "2025-12-31T00:00:00.000Z")

    def test_skip_when_mtime_unchanged_and_no_pending_new(self) -> None:
        self.write_file(
            "todo-仕事.md",
            "- [ ] alpha\n  gtasks_id:: T9999\n",
        )
        # 1回目: T9999 が remote にないので新規作成 → gtasks_id 書き戻し
        results = sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].created, 1)
        # 2回目: 何も変わらない
        results = sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].created, 0)
        self.assertEqual(results[0].updated, 0)
        self.assertGreaterEqual(results[0].skipped, 1)

    def test_completed_status_propagated(self) -> None:
        self.write_file(
            "todo-仕事.md",
            "- [x] done\n  created:: 2025-05-01\n  completed_at:: 2025-05-02T10:00:00+09:00\n",
        )
        sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        tl = next(iter(self.backend.tasklists.values()))
        task = next(iter(self.backend.tasks[tl.id].values()))
        self.assertEqual(task["status"], "completed")
        self.assertIn("completed", task)

    def test_conflict_skip_if_google_is_newer(self) -> None:
        f = self.write_file(
            "todo-仕事.md",
            "- [ ] conflict-task\n  created:: 2025-05-01\n",
        )
        # 初回同期
        sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        
        tl = next(iter(self.backend.tasklists.values()))
        task_id = list(self.backend.tasks[tl.id].keys())[0]

        # SQLite上の last_script_written_at を固定（過去の時刻）
        state = db.get_sync_state(self.conn, str(f))
        
        # Google側でタスクが更新された（モックの updated を last_script_written_at より未来にする）
        from datetime import datetime, timezone, timedelta
        if state and state["last_script_written_at"]:
            base_dt = datetime.fromisoformat(state["last_script_written_at"].replace("Z", "+00:00"))
            newer_dt = base_dt + timedelta(minutes=5)
            self.backend.tasks[tl.id][task_id]["updated"] = newer_dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        # Obsidian側でタスクが更新された（ファイル更新）
        re_parsed = parser.parse_file(f)
        re_parsed[0].title = "conflict-task-local-edit"
        parser.update_file(f, re_parsed)

        # 2回目同期（コンフリクトでスキップされるはず）
        results = sync_obs_to_gt.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        
        self.assertEqual(results[0].updated, 0)
        self.assertGreaterEqual(results[0].skipped, 1)
        
        # Google側のタスクは上書きされていないことを確認
        task = self.backend.tasks[tl.id][task_id]
        self.assertEqual(task["title"], "conflict-task")


if __name__ == "__main__":
    unittest.main()
