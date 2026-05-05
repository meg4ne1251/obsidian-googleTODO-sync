"""Todo パーサーの単体テスト。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import parser  # noqa: E402


SAMPLE = """- [ ] MTGの議事録をまとめる
  created:: 2025-05-03
  due:: 2025-06-01
  notes::
    Aさんに確認してから書く
    テンプレートはDriveのフォルダを参照
  gtasks_id:: abc123xyz

- [ ] 環境構築ドキュメント更新
  created:: 2025-05-01
  gtasks_id:: def456uvw

- [x] キックオフMTG準備
  created:: 2025-04-28
  due:: 2025-04-30
  completed_at:: 2025-04-30T14:32:00+09:00
  gtasks_id:: ghi789rst
"""


class ParserTest(unittest.TestCase):
    def test_parse_basic(self) -> None:
        todos = parser.parse_text(SAMPLE)
        self.assertEqual(len(todos), 3)
        t1 = todos[0]
        self.assertEqual(t1.title, "MTGの議事録をまとめる")
        self.assertFalse(t1.completed)
        self.assertEqual(t1.created, "2025-05-03")
        self.assertEqual(t1.due, "2025-06-01")
        self.assertEqual(t1.gtasks_id, "abc123xyz")
        self.assertEqual(
            t1.notes,
            "Aさんに確認してから書く\nテンプレートはDriveのフォルダを参照",
        )

        t2 = todos[1]
        self.assertEqual(t2.title, "環境構築ドキュメント更新")
        self.assertIsNone(t2.due)
        self.assertIsNone(t2.notes)

        t3 = todos[2]
        self.assertTrue(t3.completed)
        self.assertEqual(t3.completed_at, "2025-04-30T14:32:00+09:00")

    def test_unordered_attrs(self) -> None:
        text = """- [ ] foo
  gtasks_id:: zzz
  due:: 2025-12-31
  created:: 2025-01-01
"""
        todos = parser.parse_text(text)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].created, "2025-01-01")
        self.assertEqual(todos[0].gtasks_id, "zzz")
        self.assertEqual(todos[0].due, "2025-12-31")

    def test_empty_file(self) -> None:
        self.assertEqual(parser.parse_text(""), [])

    def test_missing_attrs(self) -> None:
        text = "- [ ] minimal\n"
        todos = parser.parse_text(text)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0].title, "minimal")
        self.assertIsNone(todos[0].created)

    def test_serialize_round_trip(self) -> None:
        todos = parser.parse_text(SAMPLE)
        text = parser.serialize_todos(todos)
        re_parsed = parser.parse_text(text)
        self.assertEqual(len(re_parsed), 3)
        for orig, rt in zip(todos, re_parsed):
            self.assertEqual(orig.title, rt.title)
            self.assertEqual(orig.completed, rt.completed)
            self.assertEqual(orig.created, rt.created)
            self.assertEqual(orig.due, rt.due)
            self.assertEqual(orig.notes, rt.notes)
            self.assertEqual(orig.gtasks_id, rt.gtasks_id)

    def test_archived_from_attr(self) -> None:
        text = """- [x] arch
  archived_from:: todo-仕事.md
  gtasks_id:: x
"""
        todos = parser.parse_text(text)
        self.assertEqual(todos[0].archived_from, "todo-仕事.md")

    def test_filename_helpers(self) -> None:
        self.assertEqual(parser.list_name_from_filename("todo-仕事.md"), "仕事")
        self.assertEqual(
            parser.list_name_from_filename("archives/todo-仕事-アーカイブ.md"), "仕事"
        )
        self.assertIsNone(parser.list_name_from_filename("readme.md"))

    def test_find_todo_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "todo-仕事.md").write_text("- [ ] x\n", encoding="utf-8")
            (root / "todo-個人.md").write_text("- [ ] y\n", encoding="utf-8")
            (root / "archives").mkdir()
            (root / "archives" / "todo-仕事-アーカイブ.md").write_text(
                "- [x] arch\n", encoding="utf-8"
            )
            (root / "other.md").write_text("none\n", encoding="utf-8")
            actives = parser.find_todo_files(root)
            self.assertEqual(len(actives), 2)
            for p in actives:
                self.assertTrue(parser.is_active_todo_file(p))
            archives = parser.find_archive_files(root)
            self.assertEqual(len(archives), 1)
            self.assertTrue(parser.is_archive_file(archives[0]))

    def test_update_file_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "todo-test.md"
            todos = [
                parser.Todo(title="A", created="2025-01-01"),
                parser.Todo(title="B", completed=True, completed_at="2025-01-02T00:00:00+09:00"),
            ]
            parser.update_file(f, todos)
            text = f.read_text(encoding="utf-8")
            self.assertIn("- [ ] A", text)
            self.assertIn("- [x] B", text)
            self.assertIn("completed_at:: 2025-01-02T00:00:00+09:00", text)

    def test_upsert_todo(self) -> None:
        existing = parser.parse_text(SAMPLE)
        updated = parser.Todo(
            title="MTGの議事録をまとめる(更新)",
            created="2025-05-03",
            gtasks_id="abc123xyz",
        )
        new = parser.upsert_todo(existing, updated)
        self.assertEqual(len(new), 3)
        self.assertEqual(new[0].title, "MTGの議事録をまとめる(更新)")

        added = parser.upsert_todo(
            existing, parser.Todo(title="新規", gtasks_id="newid")
        )
        self.assertEqual(len(added), 4)
        self.assertEqual(added[-1].gtasks_id, "newid")

    def test_remove_by_gtasks_id(self) -> None:
        existing = parser.parse_text(SAMPLE)
        removed = parser.remove_todo_by_gtasks_id(existing, "abc123xyz")
        self.assertEqual(len(removed), 2)
        self.assertNotIn("abc123xyz", [t.gtasks_id for t in removed])


if __name__ == "__main__":
    unittest.main()
