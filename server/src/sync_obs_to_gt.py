"""Obsidian → Google Tasks 同期。仕様書 §7「Obsidian → Google Tasks」準拠。"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import db, locks, mapping, parser
from .config import Config
from .gtasks import Backend, TaskList, find_or_create_tasklist
from .livesync import LivesyncCli

logger = logging.getLogger(__name__)


@dataclass
class FileSyncResult:
    file: Path
    list_name: str
    created: int = 0
    updated: int = 0
    skipped: int = 0


def _build_remote_index(backend: Backend, tasklist_id: str) -> Dict[str, dict]:
    """gtasks_id → task の dict を返す。"""
    tasks = backend.list_tasks(tasklist_id, show_completed=True, show_hidden=True)
    return {t["id"]: t for t in tasks}


def sync_file(
    file_path: Path,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
) -> FileSyncResult:
    list_name = parser.list_name_from_filename(file_path.name)
    if list_name is None:
        raise ValueError(f"Unsupported filename: {file_path}")

    tl: TaskList = find_or_create_tasklist(backend, list_name)
    todos = parser.parse_file(file_path)
    remote_index = _build_remote_index(backend, tl.id)

    result = FileSyncResult(file=file_path, list_name=list_name)
    file_changed = False

    # mtime で全体スキップ判定（最後にスクリプトが書き込んだ後の変更がないなら何もしない）
    state = db.get_sync_state(conn, str(file_path))
    file_mtime = str(file_path.stat().st_mtime) if file_path.exists() else None
    if state and state["last_obsidian_mtime"] == file_mtime:
        # mtime に変更がない場合でも、新規 (gtasks_id 未付与) のエントリがあれば処理を継続
        has_pending_new = any(t.gtasks_id is None for t in todos)
        if not has_pending_new:
            logger.debug("No mtime change for %s, skipping", file_path)
            result.skipped = len(todos)
            return result

    for idx, todo in enumerate(todos):
        body = mapping.todo_to_gtask_body(todo)
        if todo.gtasks_id and todo.gtasks_id in remote_index:
            backend.update_task(tl.id, todo.gtasks_id, body)
            result.updated += 1
        elif todo.gtasks_id and todo.gtasks_id not in remote_index:
            # ID あるが Google 側で削除済み。再作成して ID 更新。
            created = backend.insert_task(tl.id, body)
            todo.gtasks_id = created["id"]
            todos[idx] = todo
            file_changed = True
            result.created += 1
        else:
            created = backend.insert_task(tl.id, body)
            todo.gtasks_id = created["id"]
            todos[idx] = todo
            file_changed = True
            result.created += 1

    if file_changed:
        parser.update_file(file_path, todos)
        db.mark_script_written(conn, str(file_path))
    # 直近 mtime 記録
    new_mtime = str(file_path.stat().st_mtime) if file_path.exists() else None
    db.upsert_sync_state(conn, str(file_path), last_obsidian_mtime=new_mtime)
    return result


def sync_all(
    cfg: Config,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
    livesync: Optional[LivesyncCli] = None,
) -> List[FileSyncResult]:
    """全 todo-*.md を走査して Google Tasks に反映する。

    呼び出し側で `livesync_vault` ロックを取得済み・解放することを前提とする。
    """
    if livesync is not None:
        livesync.sync_pull()
    files = parser.find_todo_files(cfg.paths.vault_dir)
    results: List[FileSyncResult] = []
    for f in files:
        try:
            res = sync_file(f, backend=backend, conn=conn)
            results.append(res)
        except Exception:
            logger.exception("Sync failed: %s", f)
    if livesync is not None:
        livesync.push_sync()
    return results


# ---------------------------------------------------------------------------
# CLI エントリ
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser_arg = argparse.ArgumentParser(description="Obsidian → Google Tasks sync")
    parser_arg.add_argument("--config", default=None)
    parser_arg.add_argument("--no-livesync", action="store_true",
                            help="livesync CLI を呼び出さない（ローカル検証用）")
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
            "synced file=%s list=%s created=%d updated=%d skipped=%d",
            r.file, r.list_name, r.created, r.updated, r.skipped,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
