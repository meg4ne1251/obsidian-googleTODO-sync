"""Google Tasks → Obsidian 同期。仕様書 §7「Google Tasks → Obsidian」準拠。

- `last_google_updated`（リスト単位）より新しいタスクのみ取得
- 競合判定：`google_updated_at` vs `last_script_written_at`
- アーカイブ対象（`archived_tasks` テーブルにある ID）が **未完了に戻っている** 場合は
  archives/ から復元する
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import db, locks, mapping, parser
from .config import Config
from .gtasks import Backend, TaskList
from .livesync import LivesyncCli

logger = logging.getLogger(__name__)


SYNC_KEY_FMT = "gt-list:{list_name}"


@dataclass
class GtToObsResult:
    list_name: str
    updated: int = 0
    inserted: int = 0
    restored: int = 0
    conflicts_skipped: int = 0


def _to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _find_existing_in_files(
    todos_by_file: Dict[Path, List[parser.Todo]], gtasks_id: str
) -> Optional[Tuple[Path, int]]:
    for path, todos in todos_by_file.items():
        for idx, t in enumerate(todos):
            if t.gtasks_id == gtasks_id:
                return path, idx
    return None


def sync_list(
    list_name: str,
    tasklist: TaskList,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
    vault_dir: Path,
) -> GtToObsResult:
    state_key = SYNC_KEY_FMT.format(list_name=list_name)
    state = db.get_sync_state(conn, state_key)
    last_updated = state["last_google_updated"] if state else None

    google_tasks = backend.list_tasks(
        tasklist.id, show_completed=True, show_hidden=True, updated_min=last_updated
    )

    result = GtToObsResult(list_name=list_name)
    if not google_tasks:
        return result

    target_file = vault_dir / f"todo-{list_name}.md"
    archive_file = vault_dir / "archives" / f"todo-{list_name}-アーカイブ.md"
    archived_ids = db.list_archived_ids(conn)

    # 既存ファイル（active と archive 両方）の Todo 情報をロードする
    todos_by_file: Dict[Path, List[parser.Todo]] = {}
    if target_file.exists():
        todos_by_file[target_file] = parser.parse_file(target_file)
    else:
        todos_by_file[target_file] = []
    if archive_file.exists():
        todos_by_file[archive_file] = parser.parse_file(archive_file)

    file_changed: set = set()
    written_ts = state["last_script_written_at"] if state else None
    last_script_dt = _to_dt(written_ts)

    for raw in google_tasks:
        gid = raw["id"]
        google_updated_dt = _to_dt(raw.get("updated"))

        is_completed = raw.get("status") == "completed"

        # アーカイブ済 ID が未完了に戻ったら復元
        if gid in archived_ids and not is_completed:
            existing_archive = _find_existing_in_files(
                {p: todos for p, todos in todos_by_file.items() if p == archive_file}, gid
            )
            if existing_archive is not None:
                arch_path, arch_idx = existing_archive
                archived_todo = todos_by_file[arch_path][arch_idx]
                origin = archived_todo.archived_from or f"todo-{list_name}.md"
                origin_path = vault_dir / origin
                if origin_path not in todos_by_file:
                    todos_by_file[origin_path] = parser.parse_file(origin_path)
                # アーカイブから削除
                todos_by_file[arch_path] = [
                    t for i, t in enumerate(todos_by_file[arch_path]) if i != arch_idx
                ]
                file_changed.add(arch_path)
                # 復元先に再追加（remote の最新を反映）
                remote_todo = mapping.gtask_to_todo(raw)
                merged = mapping.merge_from_remote(archived_todo, remote_todo)
                merged.archived_from = None
                todos_by_file[origin_path] = parser.upsert_todo(
                    todos_by_file[origin_path], merged
                )
                file_changed.add(origin_path)
                db.remove_archived(conn, gid)
                result.restored += 1
                continue

        # アーカイブ済かつ完了のままなら無視（誤検知防止）
        if gid in archived_ids and is_completed:
            continue

        existing = _find_existing_in_files(todos_by_file, gid)
        remote_todo = mapping.gtask_to_todo(raw)

        if existing is None:
            # 新規 → アクティブファイルへ追加
            todos_by_file.setdefault(target_file, [])
            todos_by_file[target_file].append(remote_todo)
            file_changed.add(target_file)
            result.inserted += 1
            continue

        path, idx = existing
        local = todos_by_file[path][idx]

        # 競合判定：last_script_written_at より google_updated が古ければスキップ
        if (
            last_script_dt is not None
            and google_updated_dt is not None
            and google_updated_dt <= last_script_dt
        ):
            result.conflicts_skipped += 1
            continue

        merged = mapping.merge_from_remote(local, remote_todo)
        if path == archive_file:
            # アーカイブ内の更新は archived_from を保つ
            merged.archived_from = local.archived_from
        todos_by_file[path][idx] = merged
        file_changed.add(path)
        result.updated += 1

    # ファイル書き込み
    for path in file_changed:
        parser.update_file(path, todos_by_file[path])

    # 状態更新
    if file_changed:
        db.mark_script_written(conn, state_key)

    # last_google_updated を最大値で更新
    new_max = max(
        (raw.get("updated") for raw in google_tasks if raw.get("updated")), default=last_updated
    )
    if new_max:
        db.upsert_sync_state(conn, state_key, last_google_updated=new_max)

    return result


def sync_all(
    cfg: Config,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
    livesync: Optional[LivesyncCli] = None,
) -> List[GtToObsResult]:
    if livesync is not None:
        livesync.sync_pull()
    tasklists = backend.list_tasklists()
    results: List[GtToObsResult] = []
    for tl in tasklists:
        try:
            res = sync_list(
                tl.title, tl, backend=backend, conn=conn, vault_dir=cfg.paths.vault_dir
            )
            results.append(res)
        except Exception:
            logger.exception("Sync failed for list %s", tl.title)
    if livesync is not None:
        livesync.push_sync()
    return results


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser_arg = argparse.ArgumentParser(description="Google Tasks → Obsidian sync")
    parser_arg.add_argument("--config", default=None)
    parser_arg.add_argument("--no-livesync", action="store_true")
    args = parser_arg.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.load(args.config)
    db.initialize(cfg.paths.db_path)
    conn = db.connect(cfg.paths.db_path)

    livesync_cli = None if args.no_livesync else LivesyncCli(
        cli_command=cfg.livesync.cli_command,
        timeout_sec=cfg.livesync.timeout_sec,
    )

    from .gtasks import GoogleApiBackend
    backend = GoogleApiBackend(
        credentials_file=cfg.google.credentials_file,
        token_file=cfg.google.token_file,
        scopes=cfg.google.scopes,
    )

    with locks.lock(
        conn,
        locks.LIVESYNC_VAULT,
        timeout_sec=cfg.locks.timeout_sec,
        retry_interval_sec=cfg.locks.retry_interval_sec,
        max_retry=cfg.locks.max_retry,
    ):
        results = sync_all(cfg, backend=backend, conn=conn, livesync=livesync_cli)

    for r in results:
        logger.info(
            "list=%s updated=%d inserted=%d restored=%d conflicts_skipped=%d",
            r.list_name, r.updated, r.inserted, r.restored, r.conflicts_skipped,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
