"""整合性検証システムのテスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import db, verify  # noqa: E402
from src.config import (Config, GoogleConfig, LivesyncConfig, LocksConfig,  # noqa: E402
                        LoggingConfig, PathsConfig, VerifyConfig, ZabbixConfig)
from src.gtasks import InMemoryBackend  # noqa: E402


def make_cfg(tmp: Path, *, webhook_url: str = "") -> Config:
    vault = tmp / "vault"
    vault.mkdir(exist_ok=True)
    return Config(
        paths=PathsConfig(vault_dir=vault, db_path=tmp / "s.sqlite", log_dir=tmp / "log"),
        livesync=LivesyncConfig(npm="npm", cli_dir=".", db_dir=".", timeout_sec=10),
        google=GoogleConfig(credentials_file=tmp / "c.json", token_file=tmp / "t.json", scopes=[]),
        locks=LocksConfig(),
        verify=VerifyConfig(webhook_url=webhook_url, zabbix=ZabbixConfig()),
        logging=LoggingConfig(),
    )


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.cfg = make_cfg(self.tmp)
        self.backend = InMemoryBackend()
        self.conn = db.connect(self.cfg.paths.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_passes_when_in_sync(self) -> None:
        tl = self.backend.create_tasklist("仕事")
        t = self.backend.insert_task(tl.id, {"title": "x", "status": "needsAction"})
        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text(f"- [ ] x\n  gtasks_id:: {t['id']}\n", encoding="utf-8")
        report = verify.verify(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(report.existence_mismatches, [])
        self.assertEqual(report.field_mismatches, [])

    def test_obsidian_only(self) -> None:
        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text("- [ ] orphan\n  gtasks_id:: ZZZ\n", encoding="utf-8")
        report = verify.verify(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(len(report.existence_mismatches), 1)
        self.assertEqual(report.existence_mismatches[0].pattern, "obsidian_only")
        self.assertEqual(report.existence_mismatches[0].gtasks_id, "ZZZ")

    def test_gtasks_only(self) -> None:
        tl = self.backend.create_tasklist("仕事")
        self.backend.insert_task(tl.id, {"title": "remote orphan", "status": "needsAction"})
        report = verify.verify(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(len(report.existence_mismatches), 1)
        self.assertEqual(report.existence_mismatches[0].pattern, "gtasks_only")

    def test_field_mismatch(self) -> None:
        tl = self.backend.create_tasklist("仕事")
        t = self.backend.insert_task(
            tl.id,
            {"title": "remote", "status": "needsAction",
             "due": "2025-12-31T00:00:00.000Z"},
        )
        f = self.cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text(
            f"- [x] local\n  due:: 2025-01-01\n  gtasks_id:: {t['id']}\n",
            encoding="utf-8",
        )
        report = verify.verify(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(report.existence_mismatches, [])
        self.assertEqual(len(report.field_mismatches), 1)
        diff = report.field_mismatches[0].fields
        self.assertIn("title", diff)
        self.assertIn("due", diff)
        self.assertIn("status", diff)

    def test_archived_excluded(self) -> None:
        tl = self.backend.create_tasklist("仕事")
        t = self.backend.insert_task(tl.id, {"title": "done",
                                             "status": "completed",
                                             "completed": "2024-01-01T00:00:00.000Z"})
        # アーカイブ済として登録 → Obsidian 側にいなくても無視される
        db.add_archived(self.conn, t["id"], "仕事")
        report = verify.verify(self.cfg, backend=self.backend, conn=self.conn)
        self.assertEqual(report.existence_mismatches, [])

    def test_webhook_only_existence(self) -> None:
        cfg = make_cfg(self.tmp, webhook_url="https://example.com/hook")
        # Field mismatch のみ → Webhook 送信なし
        tl = self.backend.create_tasklist("仕事")
        t = self.backend.insert_task(
            tl.id, {"title": "x", "status": "needsAction"}
        )
        f = cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text(f"- [ ] DIFF\n  gtasks_id:: {t['id']}\n", encoding="utf-8")
        report = verify.verify(cfg, backend=self.backend, conn=self.conn)
        # 不一致：title だけ → field_mismatch
        self.assertEqual(report.existence_mismatches, [])
        self.assertEqual(len(report.field_mismatches), 1)
        # 送信せず
        session = MagicMock()
        sent = verify.post_webhook(cfg.verify.webhook_url, report, session=session)
        self.assertFalse(sent)
        session.post.assert_not_called()

    def test_webhook_sends_existence(self) -> None:
        cfg = make_cfg(self.tmp, webhook_url="https://example.com/hook")
        f = cfg.paths.vault_dir / "todo-仕事.md"
        f.write_text("- [ ] orphan\n  gtasks_id:: AAA\n", encoding="utf-8")
        report = verify.verify(cfg, backend=self.backend, conn=self.conn)
        self.assertTrue(report.has_existence_alerts)
        session = MagicMock()
        session.post.return_value.raise_for_status = lambda: None
        sent = verify.post_webhook(cfg.verify.webhook_url, report, session=session)
        self.assertTrue(sent)
        session.post.assert_called_once()
        called_kwargs = session.post.call_args.kwargs
        self.assertIn("alerts", called_kwargs["json"])
        self.assertEqual(called_kwargs["json"]["alerts"][0]["pattern"], "obsidian_only")

    def test_zabbix_sender(self) -> None:
        cfg_z = make_cfg(self.tmp)
        cfg_z.verify.zabbix.enabled = True
        cfg_z.verify.zabbix.server = "zabbix"
        cfg_z.verify.zabbix.host = "h"
        cfg_z.verify.zabbix.item_count = "gtodo.count"
        cfg_z.verify.zabbix.item_log = "gtodo.log"
        f = cfg_z.paths.vault_dir / "todo-仕事.md"
        f.write_text("- [ ] orphan\n  gtasks_id:: AAA\n", encoding="utf-8")
        report = verify.verify(cfg_z, backend=self.backend, conn=self.conn)
        runner = MagicMock()
        runner.return_value = MagicMock(returncode=0, stderr="", stdout="")
        sent = verify.send_zabbix(report, cfg_z.verify.zabbix, runner=runner)
        self.assertTrue(sent)
        runner.assert_called_once()
        cmd = runner.call_args.args[0]
        self.assertIn("zabbix_sender", cmd[0])
        self.assertIn("zabbix", cmd)


if __name__ == "__main__":
    unittest.main()
