"""livesync CLI ラッパー。"""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


class LivesyncError(RuntimeError):
    pass


class LivesyncCli:
    """livesync CLI のラッパー。`sync` / `mirror` / `pull` / `push` を呼び出す。

    呼び出し形式:
      npm --prefix <cli_dir> run cli -- <db_dir> <subcommand> [<vault_dir>]

    テストでは `runner` を差し替えて副作用を抑制できる。
    """

    def __init__(
        self,
        npm: str = "/usr/bin/npm",
        cli_dir: str = "",
        db_dir: str = "",
        vault_dir: str = "",
        timeout_sec: int = 300,
        runner=None,
    ) -> None:
        self.npm = npm
        self.cli_dir = cli_dir
        self.db_dir = db_dir
        self.vault_dir = vault_dir
        self.timeout_sec = timeout_sec
        self._runner = runner or self._default_runner

    def _default_runner(self, argv: Sequence[str]) -> int:
        logger.info("livesync-cli %s", " ".join(shlex.quote(a) for a in argv))
        try:
            res = subprocess.run(
                list(argv),
                timeout=self.timeout_sec,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise LivesyncError(
                f"npm not found: {self.npm}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LivesyncError(
                f"livesync CLI timed out: {' '.join(argv)}"
            ) from exc
        if res.returncode != 0:
            raise LivesyncError(
                f"livesync CLI failed (rc={res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
            )
        if res.stdout:
            logger.debug("stdout: %s", res.stdout.strip())
        return res.returncode

    def _run(self, subcommand: str, *args: str) -> None:
        argv: List[str] = [self.npm, "--prefix", self.cli_dir, "run", "cli", "--", self.db_dir, subcommand, *args]
        self._runner(argv)

    def sync(self) -> None:
        self._run("sync")

    def mirror(self) -> None:
        self._run("mirror", self.vault_dir)

    def pull(self) -> None:
        self._run("pull", self.vault_dir)

    def push(self) -> None:
        self._run("push", self.vault_dir)

    # 高レベルのフロー：spec セクション7「明示的呼び出し」
    def sync_pull(self) -> None:
        self.sync()
        self.pull()

    def push_sync(self) -> None:
        self.push()
        self.sync()
