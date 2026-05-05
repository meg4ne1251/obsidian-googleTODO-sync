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

    実際の CLI が未インストールの環境では `cli_command` が呼び出し可能でない
    ため例外となる。テストでは `runner` を差し替えて副作用を抑制できる。
    """

    def __init__(
        self,
        cli_command: str = "livesync-cli",
        timeout_sec: int = 300,
        cwd: Optional[Path] = None,
        runner=None,
    ) -> None:
        self.cli_command = cli_command
        self.timeout_sec = timeout_sec
        self.cwd = cwd
        self._runner = runner or self._default_runner

    def _default_runner(self, argv: Sequence[str]) -> int:
        logger.info("livesync-cli %s", " ".join(shlex.quote(a) for a in argv[1:]))
        try:
            res = subprocess.run(
                list(argv),
                cwd=self.cwd,
                timeout=self.timeout_sec,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise LivesyncError(
                f"livesync CLI not found: {self.cli_command}"
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
        argv: List[str] = [self.cli_command, subcommand, *args]
        self._runner(argv)

    def sync(self) -> None:
        self._run("sync")

    def mirror(self) -> None:
        self._run("mirror")

    def pull(self) -> None:
        self._run("pull")

    def push(self) -> None:
        self._run("push")

    # 高レベルのフロー：spec セクション7「明示的呼び出し」
    def sync_pull(self) -> None:
        self.sync()
        self.pull()

    def push_sync(self) -> None:
        self.push()
        self.sync()
