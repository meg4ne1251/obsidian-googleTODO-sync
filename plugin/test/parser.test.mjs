// プラグイン用パーサーの自己完結テスト。
// TypeScript ソースをコピーしたものを Node.js から動かす形ではなく、esbuild で
// 関数をビルドした出力を直接検証する代わりに、ソースを ts-node 等なしで動かす
// ため、parser.ts の純粋関数をそのまま動的 import するため事前にトランスパイル
// 済みファイルが必要。テスト時のみ esbuild 経由で簡易ビルドする。

import { test } from "node:test";
import assert from "node:assert/strict";
import esbuild from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import fs from "node:fs/promises";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../src/parser.ts");

async function loadParser() {
    const out = path.join(tmpdir(), `gtodo-parser-${process.pid}.mjs`);
    await esbuild.build({
        entryPoints: [SRC],
        bundle: false,
        format: "esm",
        target: "es2020",
        outfile: out,
    });
    const mod = await import(out);
    await fs.unlink(out).catch(() => {});
    return mod;
}

const SAMPLE = `- [ ] MTGの議事録をまとめる
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
`;

test("parseText extracts 3 todos", async () => {
    const { parseText } = await loadParser();
    const todos = parseText(SAMPLE);
    assert.equal(todos.length, 3);
    assert.equal(todos[0].title, "MTGの議事録をまとめる");
    assert.equal(todos[0].created, "2025-05-03");
    assert.equal(todos[0].due, "2025-06-01");
    assert.equal(todos[0].gtasksId, "abc123xyz");
    assert.equal(todos[0].notes, "Aさんに確認してから書く\nテンプレートはDriveのフォルダを参照");

    assert.equal(todos[1].title, "環境構築ドキュメント更新");
    assert.equal(todos[1].due, null);

    assert.equal(todos[2].completed, true);
    assert.equal(todos[2].completedAt, "2025-04-30T14:32:00+09:00");
});

test("serializeTodo round trip", async () => {
    const { parseText, serializeTodo } = await loadParser();
    const todos = parseText(SAMPLE);
    for (const t of todos) {
        const s = serializeTodo(t);
        const reparsed = parseText(s + "\n");
        assert.equal(reparsed.length, 1);
        assert.equal(reparsed[0].title, t.title);
        assert.equal(reparsed[0].created, t.created);
        assert.equal(reparsed[0].due, t.due);
        assert.equal(reparsed[0].notes, t.notes);
        assert.equal(reparsed[0].gtasksId, t.gtasksId);
    }
});

test("toggleCompletion adds completed_at on completion", async () => {
    const { parseText, toggleCompletion } = await loadParser();
    const t = parseText("- [ ] x\n")[0];
    const completed = toggleCompletion(t, new Date("2025-05-03T05:00:00Z"));
    assert.equal(completed.completed, true);
    assert.match(completed.completedAt, /^2025-05-03T14:00:00\+09:00$/);
    const undone = toggleCompletion(completed);
    assert.equal(undone.completed, false);
    assert.equal(undone.completedAt, null);
});

test("replaceTodoBlock updates only target block", async () => {
    const { parseText, replaceTodoBlock, toggleCompletion } = await loadParser();
    const todos = parseText(SAMPLE);
    const updated = toggleCompletion(todos[1], new Date("2025-05-03T05:00:00Z"));
    const out = replaceTodoBlock(SAMPLE, todos[1], updated);
    const re = parseText(out);
    assert.equal(re.length, 3);
    assert.equal(re[1].title, "環境構築ドキュメント更新");
    assert.equal(re[1].completed, true);
    assert.equal(re[0].title, todos[0].title);
});

test("appendTodoBlock keeps existing tasks", async () => {
    const { parseText, appendTodoBlock, makeNewTodo } = await loadParser();
    const out = appendTodoBlock(SAMPLE, makeNewTodo("新規タスク", "2099-01-01", "memo"));
    const todos = parseText(out);
    assert.equal(todos.length, 4);
    assert.equal(todos[3].title, "新規タスク");
    assert.equal(todos[3].due, "2099-01-01");
});

test("isActiveTodoPath logic", async () => {
    const { isActiveTodoPath } = await loadParser();
    assert.equal(isActiveTodoPath("todo-仕事.md"), true);
    assert.equal(isActiveTodoPath("vault/todo-個人.md"), true);
    assert.equal(isActiveTodoPath("archives/todo-仕事-アーカイブ.md"), false);
    assert.equal(isActiveTodoPath("vault/archives/todo-仕事-アーカイブ.md"), false);
    assert.equal(isActiveTodoPath("readme.md"), false);
});

test("listNameFromFilename", async () => {
    const { listNameFromFilename } = await loadParser();
    assert.equal(listNameFromFilename("todo-仕事.md"), "仕事");
    assert.equal(listNameFromFilename("todo-仕事-アーカイブ.md"), "仕事");
    assert.equal(listNameFromFilename("readme.md"), null);
});
