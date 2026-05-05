/**
 * Todo Markdown ブロックのパーサー / シリアライザ。
 * Python 実装 (server/src/parser.py) と等価ロジックを TypeScript に移植したもの。
 */

export interface TodoBlock {
    title: string;
    completed: boolean;
    created: string | null;
    due: string | null;
    notes: string | null;
    gtasksId: string | null;
    completedAt: string | null;
    archivedFrom: string | null;
    extraAttrs: Record<string, string>;
    /** 0-based 開始行 */
    startLine: number;
    /** 0-based 終了行 (exclusive) */
    endLine: number;
    /** リーディングスペース */
    indent: string;
}

const CHECKBOX_RE = /^(\s*)- \[( |x|X)\] (.*)$/;
const ATTR_RE = /^(\s+)(\w+):: ?(.*)$/;

export function parseText(text: string): TodoBlock[] {
    const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
    const todos: TodoBlock[] = [];
    let i = 0;
    while (i < lines.length) {
        const m = CHECKBOX_RE.exec(lines[i]);
        if (!m) {
            i++;
            continue;
        }
        const indent = m[1];
        const mark = m[2];
        const title = m[3].trim();
        const todo: TodoBlock = {
            title,
            completed: mark.toLowerCase() === "x",
            created: null,
            due: null,
            notes: null,
            gtasksId: null,
            completedAt: null,
            archivedFrom: null,
            extraAttrs: {},
            startLine: i,
            endLine: i + 1,
            indent,
        };
        const attrPrefix = indent + "  ";
        const notesPrefix = indent + "    ";

        let j = i + 1;
        while (j < lines.length) {
            const line = lines[j];
            if (line.length === 0) break;
            const am = ATTR_RE.exec(line);
            if (!am || am[1].length !== attrPrefix.length) break;
            const key = am[2];
            const value = am[3].replace(/\s+$/, "");
            if (key === "notes") {
                const notesLines: string[] = [];
                if (value.length > 0) notesLines.push(value);
                j++;
                while (j < lines.length) {
                    const nxt = lines[j];
                    if (nxt.length === 0) break;
                    if (nxt.startsWith(notesPrefix)) {
                        notesLines.push(nxt.slice(notesPrefix.length));
                        j++;
                        continue;
                    }
                    break;
                }
                todo.notes = notesLines.length ? notesLines.join("\n") : "";
                continue;
            }
            switch (key) {
                case "created": todo.created = value; break;
                case "due": todo.due = value; break;
                case "gtasks_id": todo.gtasksId = value; break;
                case "completed_at": todo.completedAt = value; break;
                case "archived_from": todo.archivedFrom = value; break;
                default: todo.extraAttrs[key] = value;
            }
            j++;
        }
        todo.endLine = j;
        todos.push(todo);
        i = j;
    }
    return todos;
}

export function serializeTodo(t: TodoBlock): string {
    const lines: string[] = [];
    const marker = t.completed ? "x" : " ";
    lines.push(`${t.indent}- [${marker}] ${t.title}`);
    const ai = t.indent + "  ";
    const ni = t.indent + "    ";
    if (t.created !== null) lines.push(`${ai}created:: ${t.created}`);
    if (t.due !== null) lines.push(`${ai}due:: ${t.due}`);
    if (t.completedAt !== null) lines.push(`${ai}completed_at:: ${t.completedAt}`);
    if (t.notes !== null) {
        lines.push(`${ai}notes::`);
        for (const n of t.notes.split("\n")) lines.push(`${ni}${n}`);
    }
    if (t.archivedFrom !== null) lines.push(`${ai}archived_from:: ${t.archivedFrom}`);
    if (t.gtasksId !== null) lines.push(`${ai}gtasks_id:: ${t.gtasksId}`);
    for (const [k, v] of Object.entries(t.extraAttrs)) {
        lines.push(`${ai}${k}:: ${v}`);
    }
    return lines.join("\n");
}

export function listNameFromFilename(name: string): string | null {
    if (name.startsWith("todo-") && name.endsWith("-アーカイブ.md")) {
        return name.slice("todo-".length, name.length - "-アーカイブ.md".length);
    }
    if (name.startsWith("todo-") && name.endsWith(".md")) {
        return name.slice("todo-".length, name.length - ".md".length);
    }
    return null;
}

export function isActiveTodoPath(path: string): boolean {
    if (!path.endsWith(".md")) return false;
    const segs = path.split("/");
    const fname = segs[segs.length - 1];
    if (!fname.startsWith("todo-")) return false;
    if (fname.endsWith("-アーカイブ.md")) return false;
    if (segs.includes("archives")) return false;
    return true;
}

/** 既存テキスト中の特定 Todo ブロックを差し替えた新しいテキストを返す。 */
export function replaceTodoBlock(text: string, block: TodoBlock, updated: TodoBlock): string {
    const norm = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const lines = norm.split("\n");
    updated.indent = block.indent;
    const before = lines.slice(0, block.startLine);
    const after = lines.slice(block.endLine);
    const replaced = serializeTodo(updated).split("\n");
    return [...before, ...replaced, ...after].join("\n");
}

/** 末尾に新規 Todo を追加した新しいテキストを返す。 */
export function appendTodoBlock(text: string, todo: TodoBlock): string {
    const norm = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const trimmed = norm.replace(/\n+$/, "");
    const sep = trimmed.length > 0 ? "\n\n" : "";
    return `${trimmed}${sep}${serializeTodo(todo)}\n`;
}

/** 完了/未完了をトグルし、完了化した瞬間に completed_at を JST で挿入する。 */
export function toggleCompletion(t: TodoBlock, now: Date = new Date()): TodoBlock {
    const next: TodoBlock = { ...t, extraAttrs: { ...t.extraAttrs } };
    if (t.completed) {
        next.completed = false;
        next.completedAt = null;
    } else {
        next.completed = true;
        next.completedAt = formatJst(now);
    }
    return next;
}

export function formatJst(d: Date): string {
    // JST = UTC+9
    const utcMs = d.getTime() + d.getTimezoneOffset() * 60_000;
    const jst = new Date(utcMs + 9 * 3_600_000);
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${jst.getFullYear()}-${pad(jst.getMonth() + 1)}-${pad(jst.getDate())}` +
        `T${pad(jst.getHours())}:${pad(jst.getMinutes())}:${pad(jst.getSeconds())}+09:00`;
}

export function todayJst(now: Date = new Date()): string {
    const utcMs = now.getTime() + now.getTimezoneOffset() * 60_000;
    const jst = new Date(utcMs + 9 * 3_600_000);
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${jst.getFullYear()}-${pad(jst.getMonth() + 1)}-${pad(jst.getDate())}`;
}

/** カーソル位置 (line) を含む Todo ブロックを返す。 */
export function findTodoAt(blocks: TodoBlock[], line: number): TodoBlock | null {
    for (const b of blocks) {
        if (line >= b.startLine && line < b.endLine) return b;
    }
    return null;
}

export function makeNewTodo(title: string, due: string | null, notes: string | null): TodoBlock {
    return {
        title,
        completed: false,
        created: todayJst(),
        due,
        notes,
        gtasksId: null,
        completedAt: null,
        archivedFrom: null,
        extraAttrs: {},
        startLine: -1,
        endLine: -1,
        indent: "",
    };
}
