"""Obsidian Todo ↔ Google Tasks API ペイロードの相互変換。

仕様書セクション6準拠。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from .parser import Todo


CREATED_PREFIX_RE = re.compile(r"^created:\s*(\d{4}-\d{2}-\d{2})\s*\n?")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def todo_due_to_rfc3339(due: Optional[str]) -> Optional[str]:
    """`YYYY-MM-DD` を RFC3339 (UTC, 00:00) に変換する。"""
    if not due:
        return None
    if not DATE_RE.match(due):
        # すでに RFC3339 形式と仮定
        return due
    return f"{due}T00:00:00.000Z"


def rfc3339_to_due(value: Optional[str]) -> Optional[str]:
    """Google の `due` から `YYYY-MM-DD` を抽出する。"""
    if not value:
        return None
    if DATE_RE.match(value):
        return value
    try:
        # Google Tasks の due は通常 'YYYY-MM-DDT00:00:00.000Z'
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else None


def build_notes(todo: Todo) -> Optional[str]:
    """Obsidian → Google Tasks の `notes` を組み立てる。

    `created::` がある場合は先頭行に `created: YYYY-MM-DD` を埋め込む。
    """
    parts = []
    if todo.created:
        parts.append(f"created: {todo.created}")
    if todo.notes:
        parts.append(todo.notes)
    text = "\n".join(parts)
    return text if text else None


def parse_notes(notes: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Google Tasks の `notes` から (created, notes) を取り出す。"""
    if not notes:
        return None, None
    m = CREATED_PREFIX_RE.match(notes)
    if not m:
        return None, notes
    created = m.group(1)
    rest = notes[m.end():]
    if rest.startswith("\n"):
        rest = rest[1:]
    return created, rest if rest else None


def todo_to_gtask_body(todo: Todo) -> dict:
    """Todo を Google Tasks API リクエスト Body に変換する。"""
    body: dict = {"title": todo.title}
    body["status"] = "completed" if todo.completed else "needsAction"
    notes = build_notes(todo)
    if notes is not None:
        body["notes"] = notes
    if todo.due:
        body["due"] = todo_due_to_rfc3339(todo.due)
    if todo.completed and todo.completed_at:
        # `completed_at::` (JST) → UTC RFC3339
        try:
            dt = datetime.fromisoformat(todo.completed_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            body["completed"] = dt.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            )
        except ValueError:
            body["completed"] = todo.completed_at
    return body


def gtask_to_todo(task: dict) -> Todo:
    """Google Tasks API レスポンスを Todo に変換する。"""
    created_from_notes, body_notes = parse_notes(task.get("notes"))
    completed_at = None
    if task.get("status") == "completed":
        # Google → Obsidian は JST に変換
        completed_raw = task.get("completed")
        if completed_raw:
            try:
                dt = datetime.fromisoformat(completed_raw.replace("Z", "+00:00"))
                jst = dt.astimezone(timezone(_jst_offset()))
                completed_at = jst.strftime("%Y-%m-%dT%H:%M:%S+09:00")
            except ValueError:
                completed_at = completed_raw
    return Todo(
        title=task.get("title", ""),
        completed=task.get("status") == "completed",
        created=created_from_notes,
        due=rfc3339_to_due(task.get("due")),
        notes=body_notes,
        gtasks_id=task.get("id"),
        completed_at=completed_at,
    )


def _jst_offset():
    from datetime import timedelta
    return timedelta(hours=9)


def merge_from_remote(local: Todo, remote: Todo) -> Todo:
    """Google → Obsidian 用：local の `archived_from`/`extra_attrs` を保ちつつ remote を採用。

    `created::` は Google 側 notes に埋め込みが無い場合 local の値を維持する。
    """
    out = Todo(
        title=remote.title,
        completed=remote.completed,
        created=remote.created if remote.created is not None else local.created,
        due=remote.due,
        notes=remote.notes,
        gtasks_id=remote.gtasks_id or local.gtasks_id,
        completed_at=remote.completed_at if remote.completed_at is not None else local.completed_at,
        archived_from=local.archived_from,
        extra_attrs=dict(local.extra_attrs),
        indent=local.indent,
    )
    return out
