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


def _task_needs_update(body: dict, remote: dict) -> bool:
    """ローカルの body とリモートタスクを比較し、更新が必要なら True を返す。"""
    for key in ("title", "status", "notes", "due", "completed"):
        v_body = body.get(key)
        v_remote = remote.get(key)

        if key == "notes":
            if (v_body or "").strip() != (v_remote or "").strip():
                logger.debug("Mismatch in notes for '%s': body=%r, remote=%r", body.get("title"), v_body, v_remote)
                return True
            continue

        if key == "completed":
            if v_body is None:
                # ローカル側で completed の指定がない場合（completed_at:: がない場合など）、
                # リモート側にある自動付与された完了日時と異なっていても更新しない
                continue
            if v_body != v_remote:
                logger.debug("Mismatch in completed for '%s': body=%r, remote=%r", body.get("title"), v_body, v_remote)
                return True
            continue

        if v_body != v_remote:
            logger.debug("Mismatch in %s for '%s': body=%r, remote=%r", key, body.get("title"), v_body, v_remote)
            return True
    return False


def _resolve_tasklist(
    backend: Backend,
    list_name: str,
    tasklists_cache: Optional[Dict[str, TaskList]],
) -> TaskList:
    """tasklists_cache があればそれを優先し、無ければ API を叩く。

    cache に登録されていないリスト名は新規作成し、cache にも反映する。
    """
    if tasklists_cache is None:
        return find_or_create_tasklist(backend, list_name)
    tl = tasklists_cache.get(list_name)
    if tl is None:
        tl = backend.create_tasklist(list_name)
        tasklists_cache[list_name] = tl
    return tl


def sync_file(
    file_path: Path,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
    tasklists_cache: Optional[Dict[str, TaskList]] = None,
) -> FileSyncResult:
    list_name = parser.list_name_from_filename(file_path.name)
    if list_name is None:
        raise ValueError(f"Unsupported filename: {file_path}")

    logger.info("Processing file: %s", file_path.name)
    tl: TaskList = _resolve_tasklist(backend, list_name, tasklists_cache)
    todos = parser.parse_file(file_path)
    remote_index = _build_remote_index(backend, tl.id)

    result = FileSyncResult(file=file_path, list_name=list_name)
    file_changed = False

    # mtime で全体スキップ判定（最後にスクリプトが書き込んだ後の変更がないなら何もしない）
    state = db.get_sync_state(conn, str(file_path))
    file_mtime = str(file_path.stat().st_mtime) if file_path.exists() else None
    
    # 競合判定のために前回の同期日時(last_script_written_at)を取得
    written_ts = state["last_script_written_at"] if state else None
    
    from datetime import datetime, timezone
    
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

    last_script_dt = _to_dt(written_ts)

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
            remote_task = remote_index[todo.gtasks_id]
            
            if _task_needs_update(body, remote_task):
                # 競合判定: Google 側で最後にスクリプトが書いた時間より新しく更新されている場合は上書きをスキップ
                google_updated_dt = _to_dt(remote_task.get("updated"))
                if (
                    last_script_dt is not None
                    and google_updated_dt is not None
                    and google_updated_dt > last_script_dt
                ):
                    logger.warning("  Conflict detected for task '%s'. Google Tasks has newer changes. Skipping update.", todo.title)
                    result.skipped += 1
                    continue
                    
                logger.info("  Updating task: %s", todo.title)
                # 削除されたフィールドを確実にクリアするため、明示的に null または空文字を設定
                if "notes" not in body:
                    body["notes"] = ""
                if "due" not in body:
                    body["due"] = None
                backend.update_task(tl.id, todo.gtasks_id, body)
                result.updated += 1
            else:
                result.skipped += 1
        elif todo.gtasks_id and todo.gtasks_id not in remote_index:
            # ID あるが Google 側で削除済み。再作成して ID 更新。
            logger.info("  Re-creating deleted task: %s", todo.title)
            created = backend.insert_task(tl.id, body)
            todo.gtasks_id = created["id"]
            todos[idx] = todo
            file_changed = True
            result.created += 1
        else:
            logger.info("  Creating new task: %s", todo.title)
            created = backend.insert_task(tl.id, body)
            todo.gtasks_id = created["id"]
            todos[idx] = todo
            file_changed = True
            result.created += 1

    if file_changed:
        parser.update_file(file_path, todos)
    # 書き込みがあれば last_script_written_at を更新する。
    # （次回同期での競合判定の基準時刻となる。update のみで file_changed が
    # 立たないケースでも更新しないと、google.updated が常に基準より新しいと
    # 判定されてユーザーの Obsidian 側編集が黙って捨てられる）
    if result.created > 0 or result.updated > 0:
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
    # tasklists は同期実行中に変化しない前提でキャッシュし、
    # ファイル数 N に対する list_tasklists() の呼び出しを 1 回に抑える。
    tasklists_cache: Dict[str, TaskList] = {
        tl.title: tl for tl in backend.list_tasklists()
    }
    results: List[FileSyncResult] = []
    for f in files:
        try:
            res = sync_file(
                f, backend=backend, conn=conn, tasklists_cache=tasklists_cache
            )
            results.append(res)
        except Exception:
            logger.exception("Sync failed: %s", f)
    if livesync is not None:
        modified = [r.file for r in results if r.created > 0]
        livesync.push_sync(modified)
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
        npm=cfg.livesync.npm,
        cli_dir=cfg.livesync.cli_dir,
        db_dir=cfg.livesync.db_dir,
        vault_dir=str(cfg.paths.vault_dir),
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
