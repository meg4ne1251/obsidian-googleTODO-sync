"""Google Tasks API クライアントの薄いラッパー。

ネットワーク依存を `Backend` インターフェースで抽象化することで、テスト時に
`InMemoryBackend` を差し替えられるようにしている。
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TaskList:
    id: str
    title: str


class Backend(ABC):
    """Google Tasks API への呼び出しを抽象化するインターフェース。"""

    @abstractmethod
    def list_tasklists(self) -> List[TaskList]: ...

    @abstractmethod
    def create_tasklist(self, title: str) -> TaskList: ...

    @abstractmethod
    def list_tasks(self, tasklist_id: str, *, show_completed: bool = True,
                   updated_min: Optional[str] = None,
                   show_hidden: bool = True) -> List[dict]: ...

    @abstractmethod
    def insert_task(self, tasklist_id: str, body: dict) -> dict: ...

    @abstractmethod
    def update_task(self, tasklist_id: str, task_id: str, body: dict) -> dict: ...

    @abstractmethod
    def delete_task(self, tasklist_id: str, task_id: str) -> None: ...


# ---------------------------------------------------------------------------
# 本番用：google-api-python-client 経由
# ---------------------------------------------------------------------------


class GoogleApiBackend(Backend):
    def __init__(
        self,
        credentials_file: Path,
        token_file: Path,
        scopes: List[str],
    ) -> None:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds: Optional[Credentials] = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(credentials_file), scopes
                )
                flow.redirect_uri = "http://localhost"
                auth_url, _ = flow.authorization_url(prompt="consent")
                print("\n" + "=" * 60)
                print("Google認証が必要です。以下のURLをブラウザで開いてください:")
                print(auth_url)
                print("=" * 60)
                print("認証後、リダイレクト先のURLをそのまま貼り付けてください")
                print("（'このサイトにアクセスできません' が出ても問題ありません）")
                redirect_response = input("リダイレクトURL: ").strip()
                import os as _os
                _os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
                flow.fetch_token(authorization_response=redirect_response)
                creds = flow.credentials
            token_file.parent.mkdir(parents=True, exist_ok=True)
            token_file.write_text(creds.to_json(), encoding="utf-8")
        self.service = build("tasks", "v1", credentials=creds, cache_discovery=False)

    def _execute_with_retry(self, request, max_retries=5, base_delay=1.0):
        import random
        from googleapiclient.errors import HttpError
        
        for attempt in range(max_retries):
            try:
                # Google Tasks API の「100リクエスト/100秒/ユーザー」制限に抵触しないよう、
                # リクエスト間にウェイトを入れる（安全のため1秒）
                time.sleep(1.0)
                return request.execute()
            except HttpError as e:
                # 403 (Quota Exceeded / Rate Limit), 429 (Too Many Requests), 5xx エラーの場合リトライ
                if e.resp.status in [403, 429, 500, 502, 503, 504] and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"API Rate limit or server error (status {e.resp.status}), retrying in {delay:.2f}s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise

    def list_tasklists(self) -> List[TaskList]:
        out: List[TaskList] = []
        page_token: Optional[str] = None
        while True:
            req = self.service.tasklists().list(maxResults=100, pageToken=page_token)
            resp = self._execute_with_retry(req)
            out.extend(TaskList(id=item["id"], title=item["title"]) for item in resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def create_tasklist(self, title: str) -> TaskList:
        req = self.service.tasklists().insert(body={"title": title})
        resp = self._execute_with_retry(req)
        return TaskList(id=resp["id"], title=resp["title"])

    def list_tasks(self, tasklist_id: str, *, show_completed: bool = True,
                   updated_min: Optional[str] = None,
                   show_hidden: bool = True) -> List[dict]:
        out: List[dict] = []
        page_token: Optional[str] = None
        while True:
            params = dict(
                tasklist=tasklist_id,
                maxResults=100,
                showCompleted=show_completed,
                showHidden=show_hidden,
                pageToken=page_token,
            )
            if updated_min:
                params["updatedMin"] = updated_min
            req = self.service.tasks().list(**params)
            resp = self._execute_with_retry(req)
            out.extend(resp.get("items", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                return out

    def insert_task(self, tasklist_id: str, body: dict) -> dict:
        req = self.service.tasks().insert(tasklist=tasklist_id, body=body)
        return self._execute_with_retry(req)

    def update_task(self, tasklist_id: str, task_id: str, body: dict) -> dict:
        full_body = {**body, "id": task_id}
        req = self.service.tasks().update(
            tasklist=tasklist_id, task=task_id, body=full_body
        )
        return self._execute_with_retry(req)

    def delete_task(self, tasklist_id: str, task_id: str) -> None:
        req = self.service.tasks().delete(tasklist=tasklist_id, task=task_id)
        self._execute_with_retry(req)


# ---------------------------------------------------------------------------
# テスト用：インメモリバックエンド
# ---------------------------------------------------------------------------


@dataclass
class InMemoryBackend(Backend):
    """テスト用の決定論的バックエンド。"""

    tasklists: Dict[str, TaskList] = field(default_factory=dict)
    tasks: Dict[str, Dict[str, dict]] = field(default_factory=dict)
    _id_counter: int = 0
    clock: float = 0.0

    def _new_id(self, prefix: str) -> str:
        self._id_counter += 1
        return f"{prefix}{self._id_counter:04d}"

    def _now_iso(self) -> str:
        from datetime import datetime, timezone, timedelta
        # 実時刻を使うが、self.clock を加算して必ず単調増加にする
        base = datetime.now(tz=timezone.utc) + timedelta(milliseconds=self.clock)
        self.clock += 1
        return base.strftime("%Y-%m-%dT%H:%M:%S.") + f"{base.microsecond // 1000:03d}Z"

    def list_tasklists(self) -> List[TaskList]:
        return list(self.tasklists.values())

    def create_tasklist(self, title: str) -> TaskList:
        for tl in self.tasklists.values():
            if tl.title == title:
                return tl
        tl = TaskList(id=self._new_id("L"), title=title)
        self.tasklists[tl.id] = tl
        self.tasks[tl.id] = {}
        return tl

    def list_tasks(self, tasklist_id: str, *, show_completed: bool = True,
                   updated_min: Optional[str] = None,
                   show_hidden: bool = True) -> List[dict]:
        tasks = list(self.tasks.get(tasklist_id, {}).values())
        if not show_completed:
            tasks = [t for t in tasks if t.get("status") != "completed"]
        if updated_min:
            tasks = [t for t in tasks if (t.get("updated") or "") > updated_min]
        return tasks

    def insert_task(self, tasklist_id: str, body: dict) -> dict:
        if tasklist_id not in self.tasklists:
            raise KeyError(tasklist_id)
        task_id = self._new_id("T")
        now = self._now_iso()
        task = {
            **body,
            "id": task_id,
            "updated": now,
        }
        task.setdefault("status", "needsAction")
        self.tasks.setdefault(tasklist_id, {})[task_id] = task
        return dict(task)

    def update_task(self, tasklist_id: str, task_id: str, body: dict) -> dict:
        existing = self.tasks[tasklist_id][task_id]
        merged = {**existing, **body, "id": task_id, "updated": self._now_iso()}
        self.tasks[tasklist_id][task_id] = merged
        return dict(merged)

    def delete_task(self, tasklist_id: str, task_id: str) -> None:
        self.tasks[tasklist_id].pop(task_id, None)


def find_or_create_tasklist(backend: Backend, title: str) -> TaskList:
    for tl in backend.list_tasklists():
        if tl.title == title:
            return tl
    return backend.create_tasklist(title)
