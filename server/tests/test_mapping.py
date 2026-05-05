"""Obsidian ↔ Google Tasks 属性マッピングのテスト。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import mapping  # noqa: E402
from src.parser import Todo  # noqa: E402


class MappingTest(unittest.TestCase):
    def test_due_to_rfc3339(self) -> None:
        self.assertEqual(mapping.todo_due_to_rfc3339("2025-06-01"), "2025-06-01T00:00:00.000Z")
        self.assertIsNone(mapping.todo_due_to_rfc3339(None))
        self.assertIsNone(mapping.todo_due_to_rfc3339(""))

    def test_rfc3339_to_due(self) -> None:
        self.assertEqual(mapping.rfc3339_to_due("2025-06-01T00:00:00.000Z"), "2025-06-01")
        self.assertEqual(mapping.rfc3339_to_due("2025-06-01"), "2025-06-01")
        self.assertIsNone(mapping.rfc3339_to_due(None))

    def test_build_notes_with_created(self) -> None:
        todo = Todo(title="x", created="2025-05-03", notes="line1\nline2")
        self.assertEqual(mapping.build_notes(todo), "created: 2025-05-03\nline1\nline2")

    def test_build_notes_only_created(self) -> None:
        todo = Todo(title="x", created="2025-05-03")
        self.assertEqual(mapping.build_notes(todo), "created: 2025-05-03")

    def test_build_notes_only_notes(self) -> None:
        todo = Todo(title="x", notes="hello")
        self.assertEqual(mapping.build_notes(todo), "hello")

    def test_build_notes_empty(self) -> None:
        self.assertIsNone(mapping.build_notes(Todo(title="x")))

    def test_parse_notes_with_created(self) -> None:
        c, n = mapping.parse_notes("created: 2025-05-03\nbody")
        self.assertEqual(c, "2025-05-03")
        self.assertEqual(n, "body")

    def test_parse_notes_no_created(self) -> None:
        c, n = mapping.parse_notes("just text")
        self.assertIsNone(c)
        self.assertEqual(n, "just text")

    def test_parse_notes_only_created(self) -> None:
        c, n = mapping.parse_notes("created: 2025-05-03")
        self.assertEqual(c, "2025-05-03")
        self.assertIsNone(n)

    def test_todo_to_body_round_trip(self) -> None:
        todo = Todo(
            title="MTGの議事録",
            completed=False,
            created="2025-05-03",
            due="2025-06-01",
            notes="Aさんに確認",
            gtasks_id="abc",
        )
        body = mapping.todo_to_gtask_body(todo)
        self.assertEqual(body["title"], "MTGの議事録")
        self.assertEqual(body["status"], "needsAction")
        self.assertEqual(body["due"], "2025-06-01T00:00:00.000Z")
        self.assertEqual(body["notes"], "created: 2025-05-03\nAさんに確認")

        # Google Task → Todo 復元
        body["id"] = "abc"
        body["status"] = "completed"
        body["completed"] = "2025-04-30T05:32:00.000Z"  # UTC
        restored = mapping.gtask_to_todo(body)
        self.assertEqual(restored.title, "MTGの議事録")
        self.assertTrue(restored.completed)
        self.assertEqual(restored.created, "2025-05-03")
        self.assertEqual(restored.notes, "Aさんに確認")
        self.assertEqual(restored.due, "2025-06-01")
        self.assertEqual(restored.gtasks_id, "abc")
        # JST 変換確認 (UTC 5:32 → JST 14:32)
        self.assertEqual(restored.completed_at, "2025-04-30T14:32:00+09:00")

    def test_completed_at_round_trip_no_created(self) -> None:
        body = {
            "id": "x",
            "title": "y",
            "status": "completed",
            "completed": "2025-01-02T03:04:05.000Z",
            "notes": "plain notes",
        }
        t = mapping.gtask_to_todo(body)
        self.assertIsNone(t.created)
        self.assertEqual(t.notes, "plain notes")
        self.assertEqual(t.completed_at, "2025-01-02T12:04:05+09:00")


if __name__ == "__main__":
    unittest.main()
