"""アーカイブ処理テスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import archive, db, parser  # noqa: E402
from src.config import (Config, GoogleConfig, LivesyncConfig, LocksConfig,  # noqa: E402
                        LoggingConfig, PathsConfig, VerifyConfig, ZabbixConfig)


JST = timezone(timedelta(hours=9))


def make_cfg(tmp: Path) -> Config:
    vault = tmp / "vault"
    vault.mkdir()
    return Config(
        paths=PathsConfig(vault_dir=vault, db_path=tmp / "s.sqlite", log_dir=tmp / "log"),
        livesync=LivesyncConfig(cli_command="echo", timeout_sec=10),
        google=GoogleConfig(credentials_file=tmp / "c.json", token_file=tmp / "t.json", scopes=[]),
        locks=LocksConfig(),
        verify=VerifyConfig(zabbix=ZabbixConfig()),
        logging=LoggingConfig(),
    )


class ArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cfg = make_cfg(self.tmp)
        self.conn = db.connect(self.cfg.paths.db_path)
        self.f = self.cfg.paths.vault_dir / "todo-仕事.md"

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_archive_after_one_hour(self) -> None:
        completed_long_ago = (datetime.now(JST) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
        completed_recent = (datetime.now(JST) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
        self.f.write_text(
            f"- [x] old\n  completed_at:: {completed_long_ago}\n  gtasks_id:: T0001\n\n"
            f"- [x] young\n  completed_at:: {completed_recent}\n  gtasks_id:: T0002\n\n"
            f"- [ ] active\n  gtasks_id:: T0003\n",
            encoding="utf-8",
        )
        result = archive.archive_all(self.cfg, conn=self.conn)
        self.assertEqual(result.archived, 1)

        # 元ファイルから old が消えた
        remaining = parser.parse_file(self.f)
        ids = [t.gtasks_id for t in remaining]
        self.assertIn("T0002", ids)
        self.assertIn("T0003", ids)
        self.assertNotIn("T0001", ids)

        # archives/todo-仕事-アーカイブ.md に追記された
        arch = self.cfg.paths.vault_dir / "archives" / "todo-仕事-アーカイブ.md"
        self.assertTrue(arch.exists())
        archived_todos = parser.parse_file(arch)
        self.assertEqual(len(archived_todos), 1)
        self.assertEqual(archived_todos[0].gtasks_id, "T0001")
        self.assertEqual(archived_todos[0].archived_from, "todo-仕事.md")

        # archived_tasks テーブルに記録
        self.assertIn("T0001", db.list_archived_ids(self.conn))

    def test_archive_appends_to_existing_archive_file(self) -> None:
        # 既存のアーカイブファイル
        archives_dir = self.cfg.paths.vault_dir / "archives"
        archives_dir.mkdir()
        existing_arch = archives_dir / "todo-仕事-アーカイブ.md"
        existing_arch.write_text(
            "- [x] previous\n"
            "  completed_at:: 2024-01-01T00:00:00+09:00\n"
            "  archived_from:: todo-仕事.md\n"
            "  gtasks_id:: TPREV\n",
            encoding="utf-8",
        )
        completed_old = (datetime.now(JST) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
        self.f.write_text(
            f"- [x] new\n  completed_at:: {completed_old}\n  gtasks_id:: TNEW\n",
            encoding="utf-8",
        )
        archive.archive_all(self.cfg, conn=self.conn)
        archived = parser.parse_file(existing_arch)
        ids = [t.gtasks_id for t in archived]
        self.assertEqual(ids, ["TPREV", "TNEW"])

    def test_no_action_when_nothing_to_archive(self) -> None:
        self.f.write_text("- [ ] active\n", encoding="utf-8")
        result = archive.archive_all(self.cfg, conn=self.conn)
        self.assertEqual(result.archived, 0)
        self.assertFalse((self.cfg.paths.vault_dir / "archives").exists())


if __name__ == "__main__":
    unittest.main()
