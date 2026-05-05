/** Reading View 用の MarkdownPostProcessor。 */
import { App, MarkdownPostProcessorContext, TFile } from "obsidian";
import { parseText, isActiveTodoPath, TodoBlock } from "./parser";
import { buildCardElement, buildAddTaskButton } from "./card";
import {
    toggleTodoAtLine,
    openEditModalForBlock,
    openAddModal,
    readFileText,
} from "./file_actions";

export function registerReadingView(app: App, plugin: any): void {
    plugin.registerMarkdownPostProcessor(async (
        el: HTMLElement,
        ctx: MarkdownPostProcessorContext
    ) => {
        const path = ctx.sourcePath;
        if (!path || !isActiveTodoPath(path)) return;
        const file = app.vault.getAbstractFileByPath(path);
        if (!(file instanceof TFile)) return;

        // セクションごとに渡されるので、ファイル全体を再パースして対応する Todo を見つける
        const fullText = await readFileText(app, file);
        const blocks = parseText(fullText);
        if (blocks.length === 0) return;

        const sectionInfo = ctx.getSectionInfo(el);
        if (!sectionInfo) return;

        const sectionStart = sectionInfo.lineStart;
        const sectionEnd = sectionInfo.lineEnd + 1;
        const matched = blocks.filter(
            (b) => b.startLine >= sectionStart && b.startLine < sectionEnd
        );
        if (matched.length === 0) return;

        // 元 DOM の中身を空にしてカードに置き換える
        el.empty();
        el.classList.add("gtodo-cards-container");
        for (const b of matched) {
            const card = buildCardElement(b, {
                onToggle: async () => {
                    await toggleTodoAtLine(app, file, b.startLine);
                },
                onEdit: () => openEditModalForBlock(app, file, b),
            });
            el.appendChild(card);
        }

        // ファイル末尾セクションには＋ボタンを追加
        const isLastSection = sectionEnd >= fullText.split("\n").length;
        const lastBlock = blocks[blocks.length - 1];
        if (isLastSection && matched.includes(lastBlock)) {
            el.appendChild(buildAddTaskButton(() => openAddModal(app, file)));
        }
    });
}
