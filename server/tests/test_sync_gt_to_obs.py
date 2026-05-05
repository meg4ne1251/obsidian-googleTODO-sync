"""Google Tasks → Obsidian 同期テスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, parser, sync_gt_to_obs  # noqa: E402
from src.gtasks import InMemoryBackend  # noqa: E402
from src.config import (Config, GoogleConfig, LivesyncConfig, LocksConfig,  # noqa: E402
                        LoggingConfig, PathsConfig, VerifyConfig, ZabbixConfig)


def make_cfg(tmp: Path) -> Config:
    vault = tmp / "vault"
    vault.mkdir()
    return Config(
        paths=PathsConfig(vault_dir=vault, db_path=tmp / "s.sqlite", log_dir=tmp / "log"),
        livesync=LivesyncConfig(npm="npm", cli_dir=".", db_dir=".", timeout_sec=10),
        google=GoogleConfig(credentials_file=tmp / "c.json", token_file=tmp / "t.json", scopes=[]),
        locks=LocksConfig(),
        verify=VerifyConfig(zabbix=ZabbixConfig()),
        logging=LoggingConfig(),
    )


class GtToObsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cfg = make_cfg(self.tmp)
        self.backend = InMemoryBackend()
        self.conn = db.connect(self.cfg.paths.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_inserts_new_task_into_active_file(self) -> None:
        tl = self.backend.create_tasklist("仕事")
        self.backend.insert_task(tl.id, {
            "title": "リモート発タスク",
            "status": "needsAction",
            "notes": "created: 2025-05-10\nメモ本体",
            "due": "2025-06-01T00:00:00.000Z",
        })
        results = sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].inserted, 1)

        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        text = f.read_text(encoding="utf-8")
        self.assertIn("- [ ] リモート発タスク", text)
        self.assertIn("created:: 2025-05-10", text)
        self.assertIn("notes::", text)
        self.assertIn("メモ本体", text)
        self.assertIn("due:: 2025-06-01", text)

    def test_updates_existing_task(self) -> None:
        # まず Obsidian 側にタスクを作って remote と紐付ける
        tl = self.backend.create_tasklist("仕事")
        created = self.backend.insert_task(tl.id, {"title": "old", "status": "needsAction"})
        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text(
            f"- [ ] old\n  gtasks_id:: {created['id']}\n", encoding="utf-8"
        )
        # 初回同期：last_google_updated を確立
        sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        # remote を更新
        self.backend.update_task(tl.id, created["id"], {"title": "new", "status": "needsAction"})
        results = sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].updated, 1)
        text = f.read_text(encoding="utf-8")
        self.assertIn("- [ ] new", text)

    def test_conflict_skip(self) -> None:
        # last_script_written_at を未来に設定 → google 側 update が古ければスキップ
        tl = self.backend.create_tasklist("仕事")
        created = self.backend.insert_task(tl.id, {"title": "x", "status": "needsAction"})
        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text(f"- [ ] x\n  gtasks_id:: {created['id']}\n", encoding="utf-8")
        # last_script_written_at を未来へ
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        db.upsert_sync_state(
            self.conn,
            sync_gt_to_obs.SYNC_KEY_FMT.format(list_name="仕事"),
            last_script_written_at=future,
        )
        # remote を更新
        self.backend.update_task(tl.id, created["id"], {"title": "y", "status": "needsAction"})
        results = sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].conflicts_skipped, 1)
        # ファイルは古いまま
        text = f.read_text(encoding="utf-8")
        self.assertIn("- [ ] x", text)
        self.assertNotIn("- [ ] y", text)

    def test_restoration_from_archive(self) -> None:
        # archive ファイルに完了済みタスクがある
        tl = self.backend.create_tasklist("仕事")
        created = self.backend.insert_task(tl.id, {
            "title": "復元テスト",
            "status": "completed",
            "completed": "2025-04-30T05:00:00.000Z",
        })
        gid = created["id"]
        archives_dir = self.cfg.paths.vault_dir / "archives"
        archives_dir.mkdir()
        arch_path = archives_dir / "todo-仕事-アーカイブ.md"
        arch_path.write_text(
            "- [x] 復元テスト\n"
            "  completed_at:: 2025-04-30T14:00:00+09:00\n"
            "  archived_from:: todo-仕事.md\n"
            f"  gtasks_id:: {gid}\n",
            encoding="utf-8",
        )
        db.add_archived(self.conn, gid, "仕事")

        # remote 側で未完了に戻す
        self.backend.update_task(tl.id, gid, {"title": "復元テスト", "status": "needsAction"})
        # completed フィールドを除去
        self.backend.tasks[tl.id][gid].pop("completed", None)

        results = sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(results[0].restored, 1)
        # アーカイブ DB から消えている
        self.assertNotIn(gid, db.list_archived_ids(self.conn))
        # アーカイブから消えてアクティブに戻っている
        active = self.cfg.paths.vault_dir / "todo-仕事.md"
        self.assertIn("- [ ] 復元テスト", active.read_text(encoding="utf-8"))
        # アーカイブファイルは残っているがエントリ削除済み
        self.assertEqual(arch_path.read_text(encoding="utf-8").strip(), "")

    def test_archived_completed_is_ignored(self) -> None:
        """アーカイブ済かつ完了のままのタスクは更新スキップ。"""
        tl = self.backend.create_tasklist("仕事")
        created = self.backend.insert_task(tl.id, {
            "title": "completed-archived",
            "status": "completed",
            "completed": "2025-04-01T00:00:00.000Z",
        })
        db.add_archived(self.conn, created["id"], "仕事")
        results = sync_gt_to_obs.sync_all(self.cfg, backend=self.backend, conn=self.conn)
        # active ファイルは作成されない（archived_completed なので無視）
        self.assertFalse((self.cfg.paths.vault_dir / "todo-仕事.md").exists())
        self.assertEqual(results[0].inserted, 0)


if __name__ == "__main__":
    unittest.main()
