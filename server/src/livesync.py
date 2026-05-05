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
    """livesync CLI のラッパー。`sync` / `mirror` / `push` を呼び出す。

    呼び出し形式:
      npm --prefix <cli_dir> run cli -- <db_dir> <subcommand> [args...]

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

    def push_file(self, local_path: Path) -> None:
        """ローカルの vault ファイル 1 件を DB に書き戻す。
        DB 内パスは vault_dir からの相対パスとする。"""
        rel = str(local_path.relative_to(self.vault_dir))
        self._run("push", str(local_path), rel)

    # 高レベルのフロー
    def sync_pull(self) -> None:
        """リモート CouchDB → ローカル DB → vault filesystem の順に取り込む。"""
        self.sync()
        self.mirror()

    def push_sync(self, modified_files: Optional[List[Path]] = None) -> None:
        """変更ファイルを DB に書き戻してからリモートへ同期する。"""
        for f in (modified_files or []):
            self.push_file(f)
        self.sync()
