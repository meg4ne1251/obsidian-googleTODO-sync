/** Todo カード DOM ビルダー（Reading View・CM6 ウィジェット双方で利用）。 */

import type { TodoBlock } from "./parser";
import { todayJst } from "./parser";

export interface CardCallbacks {
    onToggle?: (block: TodoBlock) => void;
    onEdit?: (block: TodoBlock) => void;
}

export function buildCardElement(
    block: TodoBlock,
    callbacks: CardCallbacks = {}
): HTMLElement {
    const root = document.createElement("div");
    root.classList.add("gtodo-card");
    if (block.completed) root.classList.add("gtodo-card--completed");

    // チェックボックス
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.classList.add("gtodo-card__checkbox");
    checkbox.checked = block.completed;
    checkbox.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        callbacks.onToggle?.(block);
    });
    root.appendChild(checkbox);

    const body = document.createElement("div");
    body.classList.add("gtodo-card__body");
    root.appendChild(body);

    const title = document.createElement("div");
    title.classList.add("gtodo-card__title");
    title.textContent = block.title;
    title.addEventListener("click", () => callbacks.onEdit?.(block));
    body.appendChild(title);

    const badges = document.createElement("div");
    badges.classList.add("gtodo-card__badges");
    body.appendChild(badges);

    if (block.due) {
        const dueBadge = document.createElement("span");
        dueBadge.classList.add("gtodo-badge", "gtodo-badge--due");
        const status = dueStatus(block.due);
        dueBadge.classList.add(`gtodo-badge--due-${status}`);
        dueBadge.textContent = `📅 ${block.due}`;
        dueBadge.addEventListener("click", () => callbacks.onEdit?.(block));
        badges.appendChild(dueBadge);
    }
    if (block.created) {
        const cBadge = document.createElement("span");
        cBadge.classList.add("gtodo-badge", "gtodo-badge--created");
        cBadge.textContent = `🗓 ${block.created}`;
        badges.appendChild(cBadge);
    }
    if (block.notes) {
        const notes = document.createElement("div");
        notes.classList.add("gtodo-card__notes");
        for (const line of block.notes.split("\n")) {
            const p = document.createElement("div");
            p.textContent = line;
            notes.appendChild(p);
        }
        notes.addEventListener("click", () => callbacks.onEdit?.(block));
        body.appendChild(notes);
    }
    return root;
}

export function dueStatus(due: string): "overdue" | "today" | "future" {
    const today = todayJst();
    if (due < today) return "overdue";
    if (due === today) return "today";
    return "future";
}

export function buildAddTaskButton(onClick: () => void): HTMLElement {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.classList.add("gtodo-add-button");
    btn.textContent = "＋ タスクを追加";
    btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        onClick();
    });
    return btn;
}
