"""同期整合性検証システム。仕様書 §8 準拠。

- 不一致の検知とレポートのみ（自動修正なし）
- 存在不一致 → Webhook / Zabbix へアラート
- フィールド不一致 → WARN ログのみ
"""
from __future__ import annotations

import json
import logging
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import db, locks, mapping, parser
from .config import Config, ZabbixConfig
from .gtasks import Backend, TaskList
from .livesync import LivesyncCli

logger = logging.getLogger("gtodo.verify")


@dataclass
class Mismatch:
    pattern: str          # "obsidian_only" | "gtasks_only" | "field_mismatch"
    gtasks_id: Optional[str]
    title: str
    list: str
    fields: Dict[str, Tuple[Any, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        out = {
            "pattern": self.pattern,
            "gtasks_id": self.gtasks_id,
            "title": self.title,
            "list": self.list,
        }
        if self.fields:
            out["fields"] = {k: {"obsidian": a, "gtasks": b} for k, (a, b) in self.fields.items()}
        return out


@dataclass
class VerifyReport:
    checked_at: str
    existence_mismatches: List[Mismatch] = field(default_factory=list)
    field_mismatches: List[Mismatch] = field(default_factory=list)

    @property
    def has_existence_alerts(self) -> bool:
        return bool(self.existence_mismatches)


def collect_obsidian(vault_dir: Path) -> Dict[str, Tuple[parser.Todo, str]]:
    """gtasks_id → (Todo, list_name) の辞書を返す。"""
    out: Dict[str, Tuple[parser.Todo, str]] = {}
    for f in parser.find_todo_files(vault_dir):
        list_name = parser.list_name_from_filename(f.name) or ""
        for todo in parser.parse_file(f):
            if todo.gtasks_id:
                out[todo.gtasks_id] = (todo, list_name)
    return out


def collect_google(backend: Backend) -> Dict[str, Tuple[dict, str]]:
    out: Dict[str, Tuple[dict, str]] = {}
    for tl in backend.list_tasklists():
        tasks = backend.list_tasks(tl.id, show_completed=True, show_hidden=True)
        for t in tasks:
            out[t["id"]] = (t, tl.title)
    return out


def _normalize_due(value: Optional[str]) -> Optional[str]:
    return mapping.rfc3339_to_due(value)


def _compare_fields(
    todo: parser.Todo, gtask: dict
) -> Dict[str, Tuple[Any, Any]]:
    diff: Dict[str, Tuple[Any, Any]] = {}
    if todo.title != gtask.get("title", ""):
        diff["title"] = (todo.title, gtask.get("title", ""))
    obs_due = todo.due
    gt_due = _normalize_due(gtask.get("due"))
    if obs_due != gt_due:
        diff["due"] = (obs_due, gt_due)
    obs_status = "completed" if todo.completed else "needsAction"
    gt_status = gtask.get("status", "needsAction")
    if obs_status != gt_status:
        diff["status"] = (obs_status, gt_status)
    return diff


def verify(
    cfg: Config,
    *,
    backend: Backend,
    conn: sqlite3.Connection,
    livesync: Optional[LivesyncCli] = None,
    now: Optional[datetime] = None,
) -> VerifyReport:
    if livesync is not None:
        livesync.sync_pull()
    obs = collect_obsidian(cfg.paths.vault_dir)
    gt = collect_google(backend)
    archived_ids = db.list_archived_ids(conn)

    report = VerifyReport(
        checked_at=(now or datetime.now(tz=timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S")
    )

    # Obsidian-only
    for gid, (todo, list_name) in obs.items():
        if gid in archived_ids:
            continue
        if gid not in gt:
            report.existence_mismatches.append(
                Mismatch(
                    pattern="obsidian_only",
                    gtasks_id=gid,
                    title=todo.title,
                    list=list_name,
                )
            )

    # Google-only
    for gid, (gtask, list_name) in gt.items():
        if gid in archived_ids:
            continue
        if gid not in obs:
            report.existence_mismatches.append(
                Mismatch(
                    pattern="gtasks_only",
                    gtasks_id=gid,
                    title=gtask.get("title", ""),
                    list=list_name,
                )
            )

    # フィールド不一致
    for gid in obs.keys() & gt.keys():
        if gid in archived_ids:
            continue
        todo, list_name = obs[gid]
        gtask, _ = gt[gid]
        diff = _compare_fields(todo, gtask)
        if diff:
            report.field_mismatches.append(
                Mismatch(
                    pattern="field_mismatch",
                    gtasks_id=gid,
                    title=todo.title,
                    list=list_name,
                    fields=diff,
                )
            )

    return report


def post_webhook(webhook_url: str, report: VerifyReport, *, session: Optional[Any] = None) -> bool:
    if not webhook_url:
        return False
    if not report.has_existence_alerts:
        return False
    payload = {
        "summary": f"タスク欠落を検出しました（{len(report.existence_mismatches)}件）",
        "checked_at": report.checked_at,
        "alerts": [m.to_dict() for m in report.existence_mismatches],
    }
    s = session or requests
    res = s.post(webhook_url, json=payload, timeout=10)
    if hasattr(res, "raise_for_status"):
        res.raise_for_status()
    return True


def send_zabbix(report: VerifyReport, zcfg: ZabbixConfig,
                runner=subprocess.run) -> bool:
    if not zcfg.enabled:
        return False
    if not (zcfg.server and zcfg.host):
        logger.warning("Zabbix enabled but server/host not configured")
        return False
    count = len(report.existence_mismatches)
    payload_lines = []
    if zcfg.item_count:
        payload_lines.append(f"{zcfg.host} {zcfg.item_count} {count}")
    if zcfg.item_log and count:
        log_text = json.dumps(
            [m.to_dict() for m in report.existence_mismatches], ensure_ascii=False
        )
        payload_lines.append(f"{zcfg.host} {zcfg.item_log} {log_text}")
    if not payload_lines:
        return False
    proc = runner(
        ["zabbix_sender", "-z", zcfg.server, "-i", "-"],
        input="\n".join(payload_lines),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        logger.error("zabbix_sender failed (rc=%d): %s", proc.returncode, proc.stderr)
        return False
    return True


def log_report(report: VerifyReport) -> None:
    if not report.existence_mismatches and not report.field_mismatches:
        logger.info("Verification passed: no mismatches")
        return
    if report.existence_mismatches:
        logger.warning(
            "Existence mismatches: %d", len(report.existence_mismatches)
        )
        for m in report.existence_mismatches:
            logger.warning("  %s", m.to_dict())
    if report.field_mismatches:
        logger.warning("Field mismatches: %d", len(report.field_mismatches))
        for m in report.field_mismatches:
            logger.warning("  %s", m.to_dict())


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Consistency verification")
    p.add_argument("--config", default=None)
    p.add_argument("--no-livesync", action="store_true")
    args = p.parse_args(argv)

    cfg = Config.load(args.config)

    # 検証用ログをコア同期と分けて出力
    cfg.paths.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = cfg.paths.log_dir / "verify.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(getattr(logging, cfg.logging.level, logging.INFO))

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

    try:
        if livesync_cli is not None:
            with locks.lock(
                conn,
                locks.LIVESYNC_VAULT,
                timeout_sec=cfg.locks.timeout_sec,
                retry_interval_sec=cfg.locks.retry_interval_sec,
                max_retry=cfg.locks.max_retry,
            ):
                report = verify(cfg, backend=backend, conn=conn, livesync=livesync_cli)
        else:
            report = verify(cfg, backend=backend, conn=conn, livesync=None)
    except Exception:
        logger.exception("Verification failed (could not execute)")
        # 検証実行不能時も Webhook へ通知
        try:
            if cfg.verify.webhook_url:
                requests.post(
                    cfg.verify.webhook_url,
                    json={"summary": "Verification could not execute", "error": True},
                    timeout=10,
                )
        except Exception:
            logger.exception("Failed to notify webhook")
        return 2

    log_report(report)

    sent = post_webhook(cfg.verify.webhook_url, report)
    if cfg.verify.zabbix.enabled:
        send_zabbix(report, cfg.verify.zabbix)

    # 終了コード: 存在不一致あり → 1、それ以外 → 0
    return 1 if report.has_existence_alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
