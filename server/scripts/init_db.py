#!/usr/bin/env python3
"""SQLite DB を初期化するスクリプト。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import Config  # noqa: E402
from src.db import initialize  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize SQLite DB for sync state.")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    initialize(cfg.paths.db_path)
    print(f"Initialized DB at: {cfg.paths.db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
