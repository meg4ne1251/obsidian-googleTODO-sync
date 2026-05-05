/** プラグインからのファイル書き換え操作（モーダル送信・トグル等）の集約。 */
import { App, MarkdownView, TFile } from "obsidian";
import {
    TodoBlock,
    parseText,
    replaceTodoBlock,
    appendTodoBlock,
    toggleCompletion,
    makeNewTodo,
    isActiveTodoPath,
} from "./parser";
import { TodoEditModal, TodoModalValues } from "./modal";

export async function readFileText(app: App, file: TFile): Promise<string> {
    return await app.vault.read(file);
}

export async function writeFileText(app: App, file: TFile, text: string): Promise<void> {
    await app.vault.modify(file, text);
}

export async function toggleTodoAtLine(app: App, file: TFile, line: number): Promise<void> {
    if (!isActiveTodoPath(file.path)) return;
    const text = await readFileText(app, file);
    const blocks = parseText(text);
    const target = blocks.find((b) => line >= b.startLine && line < b.endLine);
    if (!target) return;
    const updated = toggleCompletion(target);
    const newText = replaceTodoBlock(text, target, updated);
    await writeFileText(app, file, newText);
}

export async function applyEditModalResult(
    app: App,
    file: TFile,
    block: TodoBlock,
    values: TodoModalValues
): Promise<void> {
    const text = await readFileText(app, file);
    const updated: TodoBlock = {
        ...block,
        title: values.title.trim() || block.title,
        due: values.due,
        notes: values.notes,
    };
    const newText = replaceTodoBlock(text, block, updated);
    await writeFileText(app, file, newText);
}

export async function appendNewTodo(
    app: App,
    file: TFile,
    values: TodoModalValues
): Promise<void> {
    const text = await readFileText(app, file);
    const todo = makeNewTodo(
        values.title.trim() || "(無題)",
        values.due,
        values.notes
    );
    const newText = appendTodoBlock(text, todo);
    await writeFileText(app, file, newText);
}

export function openEditModalForBlock(
    app: App,
    file: TFile,
    block: TodoBlock
): void {
    TodoEditModal.fromBlock(app, block, async (vals) => {
        await applyEditModalResult(app, file, block, vals);
    }).open();
}

export function openAddModal(app: App, file: TFile): void {
    new TodoEditModal(
        app,
        { title: "", due: null, notes: null },
        async (vals) => {
            if (!vals.title.trim()) return;
            await appendNewTodo(app, file, vals);
        }
    ).open();
}

export function getActiveTodoFile(app: App): TFile | null {
    const view = app.workspace.getActiveViewOfType(MarkdownView);
    if (!view || !view.file) return null;
    if (!isActiveTodoPath(view.file.path)) return null;
    return view.file;
}
