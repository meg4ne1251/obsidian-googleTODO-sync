/** Todo 編集モーダル。 */
import { App, Modal, Setting } from "obsidian";
import type { TodoBlock } from "./parser";

export interface TodoModalValues {
    title: string;
    due: string | null;
    notes: string | null;
}

export class TodoEditModal extends Modal {
    private values: TodoModalValues;
    private readonly initial: TodoModalValues;
    private readonly onSubmit: (v: TodoModalValues) => void;
    private readonly onCancel?: () => void;

    constructor(
        app: App,
        initial: TodoModalValues,
        onSubmit: (v: TodoModalValues) => void,
        onCancel?: () => void
    ) {
        super(app);
        this.initial = initial;
        this.values = { ...initial };
        this.onSubmit = onSubmit;
        this.onCancel = onCancel;
    }

    static fromBlock(
        app: App,
        block: TodoBlock,
        onSubmit: (v: TodoModalValues) => void
    ): TodoEditModal {
        return new TodoEditModal(
            app,
            { title: block.title, due: block.due, notes: block.notes },
            onSubmit
        );
    }

    onOpen(): void {
        const { contentEl } = this;
        contentEl.empty();
        contentEl.addClass("gtodo-modal");

        new Setting(contentEl)
            .setName("タイトル")
            .addText((t) => {
                t.setValue(this.values.title);
                t.onChange((v) => (this.values.title = v));
                t.inputEl.style.width = "100%";
            });

        new Setting(contentEl)
            .setName("期限 (due)")
            .addText((t) => {
                t.inputEl.type = "date";
                t.setValue(this.values.due ?? "");
                t.onChange((v) => (this.values.due = v || null));
            });

        new Setting(contentEl)
            .setName("メモ (notes)")
            .addTextArea((ta) => {
                ta.inputEl.rows = 4;
                ta.inputEl.style.width = "100%";
                ta.setValue(this.values.notes ?? "");
                ta.onChange((v) => (this.values.notes = v || null));
            });

        const buttons = contentEl.createDiv({ cls: "gtodo-modal__buttons" });
        const cancelBtn = buttons.createEl("button", { text: "キャンセル" });
        cancelBtn.addEventListener("click", () => {
            this.values = { ...this.initial };
            this.onCancel?.();
            this.close();
        });
        const submitBtn = buttons.createEl("button", { text: "保存", cls: "mod-cta" });
        submitBtn.addEventListener("click", () => {
            this.onSubmit({ ...this.values });
            this.close();
        });
    }

    onClose(): void {
        this.contentEl.empty();
    }
}
