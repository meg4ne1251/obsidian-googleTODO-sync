"""Todo Markdown ブロックのパーサー / シリアライザ。

仕様書セクション2に準拠。

Block 構造:
    - [ ] {タイトル}
      created:: YYYY-MM-DD
      due:: YYYY-MM-DD
      notes::
        line1
        line2
      gtasks_id:: xxx
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# 既知の属性キー
KNOWN_ATTRS = {
    "created",
    "due",
    "notes",
    "gtasks_id",
    "completed_at",
    "archived_from",
}

CHECKBOX_RE = re.compile(r"^(\s*)- \[( |x|X)\] (.*)$")
ATTR_RE = re.compile(r"^(\s+)(\w+):: ?(.*)$")


@dataclass
class Todo:
    title: str
    completed: bool = False
    created: Optional[str] = None
    due: Optional[str] = None
    notes: Optional[str] = None
    gtasks_id: Optional[str] = None
    completed_at: Optional[str] = None
    archived_from: Optional[str] = None
    extra_attrs: dict = field(default_factory=dict)
    # ソース内での開始行・終了行（exclusive end）。書き戻し用
    start_line: int = -1
    end_line: int = -1
    # 元のインデント（チェックボックス行のリーディングスペース）
    indent: str = ""

    def to_markdown(self) -> str:
        """ブロックを Markdown 文字列にシリアライズする（末尾に改行は含まない）。"""
        lines: List[str] = []
        marker = "x" if self.completed else " "
        lines.append(f"{self.indent}- [{marker}] {self.title}")
        attr_indent = self.indent + "  "
        notes_indent = self.indent + "    "
        # 仕様の推奨順序: created, due, notes, gtasks_id, completed_at（archived_from は notes と gtasks_id の間に置く）
        if self.created is not None:
            lines.append(f"{attr_indent}created:: {self.created}")
        if self.due is not None:
            lines.append(f"{attr_indent}due:: {self.due}")
        if self.completed_at is not None:
            lines.append(f"{attr_indent}completed_at:: {self.completed_at}")
        if self.notes is not None:
            lines.append(f"{attr_indent}notes::")
            for n in self.notes.split("\n"):
                lines.append(f"{notes_indent}{n}")
        if self.archived_from is not None:
            lines.append(f"{attr_indent}archived_from:: {self.archived_from}")
        if self.gtasks_id is not None:
            lines.append(f"{attr_indent}gtasks_id:: {self.gtasks_id}")
        for k, v in self.extra_attrs.items():
            lines.append(f"{attr_indent}{k}:: {v}")
        return "\n".join(lines)


def _normalize_eol(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_text(text: str) -> List[Todo]:
    """テキスト全体から Todo ブロックの一覧を抽出する。"""
    text = _normalize_eol(text)
    lines = text.split("\n")
    todos: List[Todo] = []

    i = 0
    while i < len(lines):
        m = CHECKBOX_RE.match(lines[i])
        if not m:
            i += 1
            continue
        block_indent, mark, title = m.group(1), m.group(2), m.group(3).strip()
        todo = Todo(
            title=title,
            completed=mark.lower() == "x",
            indent=block_indent,
            start_line=i,
        )
        attr_indent_prefix = block_indent + "  "
        notes_indent_prefix = block_indent + "    "

        j = i + 1
        while j < len(lines):
            line = lines[j]
            if not line.strip():
                # 空行はブロック内の終端（次の Todo に進む）
                # ただし notes の内部空行を許容するため、後で再判定
                # ここでは attr の途中なので空行で終了
                break
            am = ATTR_RE.match(line)
            if am and len(am.group(1)) == len(attr_indent_prefix):
                key = am.group(2)
                raw_value = am.group(3).rstrip()
                if key == "notes":
                    # 値が同行にあれば1行 notes として扱う
                    if raw_value:
                        notes_lines = [raw_value]
                        j += 1
                    else:
                        notes_lines = []
                        j += 1
                    # 続くインデントが notes_indent_prefix 以上の行を取り込む
                    while j < len(lines):
                        nxt = lines[j]
                        if not nxt:
                            # notes 内の空行はそのまま取り込む
                            # ただし、次行が attr もしくは新しいブロックなら停止
                            if j + 1 < len(lines):
                                nxt2 = lines[j + 1]
                                if (
                                    CHECKBOX_RE.match(nxt2)
                                    or ATTR_RE.match(nxt2)
                                    and len(ATTR_RE.match(nxt2).group(1)) == len(attr_indent_prefix)
                                ):
                                    break
                            else:
                                break
                            notes_lines.append("")
                            j += 1
                            continue
                        if nxt.startswith(notes_indent_prefix):
                            notes_lines.append(nxt[len(notes_indent_prefix):])
                            j += 1
                            continue
                        break
                    todo.notes = "\n".join(notes_lines) if notes_lines else ""
                    continue
                # 通常属性
                if key == "created":
                    todo.created = raw_value
                elif key == "due":
                    todo.due = raw_value
                elif key == "gtasks_id":
                    todo.gtasks_id = raw_value
                elif key == "completed_at":
                    todo.completed_at = raw_value
                elif key == "archived_from":
                    todo.archived_from = raw_value
                else:
                    todo.extra_attrs[key] = raw_value
                j += 1
                continue
            # チェックボックスや非属性行に到達 → ブロック終了
            break

        todo.end_line = j
        todos.append(todo)
        i = j
    return todos


def parse_file(path: Path) -> List[Todo]:
    """ファイルから Todo を読み込む。存在しなければ空リスト。"""
    if not path.exists():
        return []
    return parse_text(path.read_text(encoding="utf-8"))


def serialize_todos(todos: List[Todo], *, trailing_newline: bool = True) -> str:
    """Todo リストを Markdown 文字列に直列化する（ブロック間は空行1行）。"""
    blocks = [t.to_markdown() for t in todos]
    out = "\n\n".join(blocks)
    if trailing_newline and out:
        out += "\n"
    return out


def list_name_from_filename(filename: str) -> Optional[str]:
    """`todo-{name}.md` から name を取り出す。アーカイブも対応。"""
    name = Path(filename).name
    if name.startswith("todo-") and name.endswith("-アーカイブ.md"):
        return name[len("todo-"): -len("-アーカイブ.md")]
    if name.startswith("todo-") and name.endswith(".md"):
        return name[len("todo-"): -len(".md")]
    return None


def is_active_todo_file(path: Path) -> bool:
    """`todo-*.md` で `archives/` 配下でない場合 True。"""
    if path.name.startswith("todo-") and path.suffix == ".md":
        # archives/ 直下は除外
        parts = path.parts
        if "archives" in parts:
            return False
        return not path.name.endswith("-アーカイブ.md")
    return False


def is_archive_file(path: Path) -> bool:
    return path.name.startswith("todo-") and path.name.endswith("-アーカイブ.md")


def find_todo_files(vault_dir: Path) -> List[Path]:
    """Vault 配下のアクティブな todo-*.md を返す（archives/ 配下は除外）。"""
    if not vault_dir.exists():
        return []
    out: List[Path] = []
    for p in vault_dir.rglob("todo-*.md"):
        if is_active_todo_file(p):
            out.append(p)
    out.sort()
    return out


def find_archive_files(vault_dir: Path) -> List[Path]:
    archives_dir = vault_dir / "archives"
    if not archives_dir.exists():
        return []
    return sorted(p for p in archives_dir.glob("todo-*-アーカイブ.md") if p.is_file())


# ---------------------------------------------------------------------------
# 差分書き戻し
# ---------------------------------------------------------------------------


def update_file(path: Path, todos: List[Todo]) -> None:
    """対象ファイルを与えられた Todo リストで上書きする。アトミック書き込み。"""
    text = serialize_todos(todos)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def upsert_todo(todos: List[Todo], updated: Todo, *, key: str = "gtasks_id") -> List[Todo]:
    """gtasks_id をキーに既存 Todo を更新、なければ末尾に追加。"""
    new_value = getattr(updated, key)
    if new_value is None:
        return todos + [updated]
    for idx, existing in enumerate(todos):
        if getattr(existing, key) == new_value:
            updated.indent = existing.indent
            todos[idx] = updated
            return todos
    return todos + [updated]


def remove_todo_by_gtasks_id(todos: List[Todo], gtasks_id: str) -> List[Todo]:
    return [t for t in todos if t.gtasks_id != gtasks_id]
