/** プラグインエントリ。 */
import { Editor, MarkdownFileInfo, MarkdownView, Plugin } from "obsidian";
import type { Extension } from "@codemirror/state";
import { registerReadingView } from "./reading";
import { buildEditorPlugin } from "./editor";
import {
    getActiveTodoFile,
    openAddModal,
    openEditModalForBlock,
    toggleTodoAtLine,
} from "./file_actions";
import { isActiveTodoPath, parseText, findTodoAt } from "./parser";

export default class GoogleTodoSyncPlugin extends Plugin {
    async onload(): Promise<void> {
        registerReadingView(this.app, this);
        this.registerEditorExtension(buildEditorPlugin(this.app) as unknown as Extension);

        this.addCommand({
            id: "add-task",
            name: "タスクを追加",
            checkCallback: (checking) => {
                const file = getActiveTodoFile(this.app);
                if (!file) return false;
                if (!checking) openAddModal(this.app, file);
                return true;
            },
        });

        this.addCommand({
            id: "toggle-complete",
            name: "カーソル位置の Todo の完了/未完了をトグル",
            editorCheckCallback: (checking, editor: Editor, ctx: MarkdownView | MarkdownFileInfo) => {
                const file = ctx.file;
                if (!file || !isActiveTodoPath(file.path)) return false;
                if (!checking) {
                    const line = editor.getCursor().line;
                    void toggleTodoAtLine(this.app, file, line);
                }
                return true;
            },
        });

        this.addCommand({
            id: "open-edit-modal",
            name: "カーソル位置の Todo の編集モーダルを開く",
            editorCheckCallback: (checking, editor: Editor, ctx: MarkdownView | MarkdownFileInfo) => {
                const file = ctx.file;
                if (!file || !isActiveTodoPath(file.path)) return false;
                const line = editor.getCursor().line;
                if (!checking) {
                    void this.app.vault.read(file).then((text) => {
                        const block = findTodoAt(parseText(text), line);
                        if (block) openEditModalForBlock(this.app, file, block);
                    });
                }
                return true;
            },
        });
    }

    onunload(): void {
        // CM6 拡張は registerEditorExtension で自動アンロード
    }
}
