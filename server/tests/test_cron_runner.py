"""cron_runner の単体テスト（livesync 呼び出しを差し替え）。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import cron_runner, db  # noqa: E402
from src.config import (Config, GoogleConfig, LivesyncConfig, LocksConfig,  # noqa: E402
                        LoggingConfig, PathsConfig, VerifyConfig, ZabbixConfig)


def make_cfg(tmp: Path) -> Config:
    return Config(
        paths=PathsConfig(vault_dir=tmp / "v", db_path=tmp / "s.sqlite", log_dir=tmp / "log"),
        livesync=LivesyncConfig(cli_command="echo", timeout_sec=10),
        google=GoogleConfig(credentials_file=tmp / "c.json", token_file=tmp / "t.json", scopes=[]),
        locks=LocksConfig(),
        verify=VerifyConfig(zabbix=ZabbixConfig()),
        logging=LoggingConfig(),
    )


class CronRunnerTest(unittest.TestCase):
    def test_runs_sync_mirror_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            calls = []
            with patch("src.cron_runner.LivesyncCli") as mock_cli:
                instance = mock_cli.return_value
                instance.sync.side_effect = lambda: calls.append("sync")
                instance.mirror.side_effect = lambda: calls.append("mirror")
                rc = cron_runner.run_periodic(cfg)
            self.assertEqual(rc, 0)
            self.assertEqual(calls, ["sync", "mirror", "sync"])

    def test_lock_released_after(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_cfg(Path(tmp))
            with patch("src.cron_runner.LivesyncCli"):
                cron_runner.run_periodic(cfg)
            conn = db.connect(cfg.paths.db_path)
            count = conn.execute("SELECT COUNT(*) FROM process_locks").fetchone()[0]
            self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
