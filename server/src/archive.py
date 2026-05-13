"""アーカイブ処理（1時間ごとの cron ジョブ）。仕様書 §7「アーカイブ処理」準拠。

- `- [x]` かつ `completed_at::` から1時間以上経過したエントリを抽出
- `archives/todo-{リスト名}-アーカイブ.md` の末尾に `archived_from::` を付与して追記
- 元ファイルから該当エントリを削除
- `archived_tasks` テーブルに INSERT
- Google Tasks 側は完了済みのまま放置
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from . import db, locks, parser
from .config import Config
from .livesync import LivesyncCli

logger = logging.getLogger(__name__)

ARCHIVE_THRESHOLD = timedelta(hours=1)


@dataclass
class ArchiveResult:
    archived: int = 0
    files_touched: List[str] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.files_touched is None:
            self.files_touched = []


def _parse_completed_at(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_ready_to_archive(todo: parser.Todo, *, now: datetime,
                         threshold: timedelta = ARCHIVE_THRESHOLD) -> bool:
    if not todo.completed:
        return False
    if not todo.completed_at:
        return False
    completed_dt = _parse_completed_at(todo.completed_at)
    if completed_dt is None:
        return False
    return now - completed_dt >= threshold


def archive_file(
    file_path: Path,
    *,
    vault_dir: Path,
    conn: sqlite3.Connection,
    now: Optional[datetime] = None,
) -> Tuple[int, List[Path]]:
    if now is None:
        now = datetime.now(tz=timezone.utc).astimezone(timezone(timedelta(hours=9)))

    todos = parser.parse_file(file_path)
    keep: List[parser.Todo] = []
    to_archive: List[parser.Todo] = []
    for t in todos:
        if _is_ready_to_archive(t, now=now):
            to_archive.append(t)
        else:
            keep.append(t)
    if not to_archive:
        return 0, []

    list_name = parser.list_name_from_filename(file_path.name)
    if list_name is None:
        return 0, []

    archives_dir = vault_dir / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archives_dir / f"todo-{list_name}-アーカイブ.md"
    existing_arch = parser.parse_file(archive_path)
    for t in to_archive:
        t.archived_from = str(file_path.relative_to(vault_dir))
        existing_arch.append(t)
        if t.gtasks_id:
            db.add_archived(conn, t.gtasks_id, list_name)

    parser.update_file(archive_path, existing_arch)
    parser.update_file(file_path, keep)
    db.mark_script_written(conn, str(file_path))
    db.mark_script_written(conn, str(archive_path))
    return len(to_archive), [file_path, archive_path]


def archive_all(
    cfg: Config,
    *,
    conn: sqlite3.Connection,
    livesync: Optional[LivesyncCli] = None,
    now: Optional[datetime] = None,
) -> ArchiveResult:
    if livesync is not None:
        livesync.sync_pull()
    files = parser.find_todo_files(cfg.paths.vault_dir)
    result = ArchiveResult()
    for f in files:
        try:
            archived, touched = archive_file(
                f, vault_dir=cfg.paths.vault_dir, conn=conn, now=now
            )
            result.archived += archived
            result.files_touched.extend(str(p) for p in touched)
        except Exception:
            logger.exception("Archive failed: %s", f)
    if livesync is not None:
        livesync.push_sync()
    return result


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Archive completed Todos older than 1h")
    p.add_argument("--config", default=None)
    p.add_argument("--no-livesync", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load(args.config)
    db.initialize(cfg.paths.db_path)
    conn = db.connect(cfg.paths.db_path)
    livesync_cli = None if args.no_livesync else LivesyncCli(
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
        result = archive_all(cfg, conn=conn, livesync=livesync_cli)

    logger.info("archived=%d files_touched=%d", result.archived, len(result.files_touched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
