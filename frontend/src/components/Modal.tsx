"use client";

import { type ReactNode, type RefObject, useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR = [
	"a[href]",
	"button:not([disabled]):not([tabindex='-1'])",
	"input:not([disabled]):not([type='hidden'])",
	"select:not([disabled])",
	"textarea:not([disabled])",
	"[tabindex]:not([tabindex='-1'])",
].join(",");

interface ModalProps {
	children: ReactNode;
	labelledBy: string;
	describedBy?: string;
	onClose: () => void;
	panelClassName?: string;
	containerClassName?: string;
	backdropClassName?: string;
	initialFocusRef?: RefObject<HTMLElement | null>;
}

export default function Modal({
	children,
	labelledBy,
	describedBy,
	onClose,
	panelClassName = "",
	containerClassName = "fixed inset-0 z-50 flex items-center justify-center",
	backdropClassName = "",
	initialFocusRef,
}: ModalProps) {
	const dialogRef = useRef<HTMLDivElement>(null);
	const onCloseRef = useRef(onClose);
	onCloseRef.current = onClose;

	useEffect(() => {
		const previouslyFocused =
			document.activeElement instanceof HTMLElement
				? document.activeElement
				: null;
		const dialog = dialogRef.current;
		const frame = window.requestAnimationFrame(() => {
			(initialFocusRef?.current ?? dialog)?.focus();
		});
		const observer = new MutationObserver(() => {
			if (dialog && !dialog.contains(document.activeElement)) dialog.focus();
		});
		if (dialog) observer.observe(dialog, { childList: true, subtree: true });

		function handleKeyDown(event: KeyboardEvent) {
			if (event.key === "Escape") {
				event.preventDefault();
				onCloseRef.current();
				return;
			}

			if (event.key !== "Tab" || !dialog) return;

			const focusable = Array.from(
				dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
			).filter((element) => element.getClientRects().length > 0);

			if (focusable.length === 0) {
				event.preventDefault();
				dialog.focus();
				return;
			}

			const first = focusable[0];
			const last = focusable[focusable.length - 1];
			if (!dialog.contains(document.activeElement)) {
				event.preventDefault();
				(event.shiftKey ? last : first).focus();
				return;
			}
			if (
				event.shiftKey &&
				(document.activeElement === first || document.activeElement === dialog)
			) {
				event.preventDefault();
				last.focus();
			} else if (!event.shiftKey && document.activeElement === last) {
				event.preventDefault();
				first.focus();
			}
		}

		document.addEventListener("keydown", handleKeyDown);
		return () => {
			window.cancelAnimationFrame(frame);
			observer.disconnect();
			document.removeEventListener("keydown", handleKeyDown);
			if (previouslyFocused?.isConnected) previouslyFocused.focus();
		};
	}, [initialFocusRef]);

	return (
		<div className={containerClassName}>
			<button
				type="button"
				aria-label="Close dialog"
				tabIndex={-1}
				className={`modal-backdrop absolute inset-0 border-0 bg-[#2e2522]/55 ${backdropClassName}`}
				onClick={onClose}
			/>
			<div
				ref={dialogRef}
				role="dialog"
				aria-modal="true"
				aria-labelledby={labelledBy}
				aria-describedby={describedBy}
				tabIndex={-1}
				className={`modal-panel relative outline-none ${panelClassName}`}
			>
				{children}
			</div>
		</div>
	);
}
