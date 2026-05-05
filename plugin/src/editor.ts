/** Live Preview (CodeMirror 6) 用の ViewPlugin / DecorationSet。 */
import {
    Decoration,
    DecorationSet,
    EditorView,
    ViewPlugin,
    ViewUpdate,
    WidgetType,
} from "@codemirror/view";
import { RangeSetBuilder } from "@codemirror/state";
import type { App, TFile } from "obsidian";
import { TodoBlock, parseText, isActiveTodoPath, replaceTodoBlock, toggleCompletion } from "./parser";
import { buildCardElement, buildAddTaskButton } from "./card";
import { openEditModalForBlock, openAddModal, getActiveTodoFile } from "./file_actions";

class TodoCardWidget extends WidgetType {
    constructor(
        private readonly block: TodoBlock,
        private readonly app: App,
        private readonly fileGetter: () => TFile | null
    ) {
        super();
    }
    eq(other: TodoCardWidget): boolean {
        return JSON.stringify(this.block) === JSON.stringify(other.block);
    }
    toDOM(_view: EditorView): HTMLElement {
        return buildCardElement(this.block, {
            onToggle: () => {
                const file = this.fileGetter();
                if (!file) return;
                this.app.vault.read(file).then((text) => {
                    const updated = toggleCompletion(this.block);
                    const next = replaceTodoBlock(text, this.block, updated);
                    return this.app.vault.modify(file, next);
                });
            },
            onEdit: () => {
                const file = this.fileGetter();
                if (file) openEditModalForBlock(this.app, file, this.block);
            },
        });
    }
    ignoreEvent(): boolean {
        return false;
    }
}

class AddButtonWidget extends WidgetType {
    constructor(private readonly app: App, private readonly fileGetter: () => TFile | null) {
        super();
    }
    eq(_other: AddButtonWidget): boolean {
        return true;
    }
    toDOM(_view: EditorView): HTMLElement {
        const wrapper = document.createElement("div");
        wrapper.classList.add("gtodo-add-wrapper");
        wrapper.appendChild(
            buildAddTaskButton(() => {
                const file = this.fileGetter();
                if (file) openAddModal(this.app, file);
            })
        );
        return wrapper;
    }
}

function buildDecorations(
    view: EditorView,
    app: App,
    fileGetter: () => TFile | null
): DecorationSet {
    const file = fileGetter();
    if (!file || !isActiveTodoPath(file.path)) {
        return Decoration.none;
    }
    const builder = new RangeSetBuilder<Decoration>();
    const docText = view.state.doc.toString();
    const blocks = parseText(docText);
    const cursorLine = view.state.doc.lineAt(view.state.selection.main.head).number - 1;

    for (const b of blocks) {
        if (cursorLine >= b.startLine && cursorLine < b.endLine) {
            // ブロック内にカーソル → 生 Markdown 表示（デコレーションを張らない）
            continue;
        }
        const fromLine = view.state.doc.line(b.startLine + 1);
        const toLine = view.state.doc.line(b.endLine);
        const widget = Decoration.replace({
            widget: new TodoCardWidget(b, app, fileGetter),
            block: true,
        });
        builder.add(fromLine.from, toLine.to, widget);
    }

    // 末尾に＋ボタンを差し込む（ブロック装飾なので末尾位置）
    if (blocks.length > 0) {
        const lastLineNumber = view.state.doc.lines;
        const lastLine = view.state.doc.line(lastLineNumber);
        const widget = Decoration.widget({
            widget: new AddButtonWidget(app, fileGetter),
            side: 1,
            block: true,
        });
        builder.add(lastLine.to, lastLine.to, widget);
    }
    return builder.finish();
}

export function buildEditorPlugin(app: App): ReturnType<typeof ViewPlugin.fromClass> {
    return ViewPlugin.fromClass(
        class {
            decorations: DecorationSet;
            private readonly fileGetter = () => getActiveTodoFile(app);
            constructor(view: EditorView) {
                this.decorations = buildDecorations(view, app, this.fileGetter);
            }
            update(update: ViewUpdate): void {
                if (
                    update.docChanged ||
                    update.viewportChanged ||
                    update.selectionSet
                ) {
                    this.decorations = buildDecorations(update.view, app, this.fileGetter);
                }
            }
        },
        {
            decorations: (v) => v.decorations,
        }
    );
}
