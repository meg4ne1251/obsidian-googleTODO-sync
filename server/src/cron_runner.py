"""定期 cron 実行用ラッパー：`livesync_vault` ロック下で `sync → mirror → sync` を実行する。"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from . import db, locks
from .config import Config
from .livesync import LivesyncCli

logger = logging.getLogger(__name__)


def run_periodic(cfg: Config) -> int:
    db.initialize(cfg.paths.db_path)
    conn = db.connect(cfg.paths.db_path)
    livesync_cli = LivesyncCli(
        npm=cfg.livesync.npm,
        cli_dir=cfg.livesync.cli_dir,
        db_dir=cfg.livesync.db_dir,
        vault_dir=str(cfg.paths.vault_dir),
        timeout_sec=cfg.livesync.timeout_sec,
    )
    with locks.lock(
        conn,
        locks.LIVESYNC_VAULT,
        timeout_sec=cfg.locks.timeout_sec,
        retry_interval_sec=cfg.locks.retry_interval_sec,
        max_retry=cfg.locks.max_retry,
    ):
        livesync_cli.sync()
        livesync_cli.mirror()
        livesync_cli.sync()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Periodic cron wrapper")
    p.add_argument("--config", default=None)
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = Config.load(args.config)
    try:
        return run_periodic(cfg)
    except Exception:
        logger.exception("cron periodic run failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
