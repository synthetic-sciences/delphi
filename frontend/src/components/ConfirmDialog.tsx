"use client";

import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title = "are you sure?",
  message,
  confirmLabel = "confirm",
  cancelLabel = "cancel",
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement>(null);

  // Focus confirm button when dialog opens
  useEffect(() => {
    if (open) confirmRef.current?.focus();
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onCancel]);

  if (!open) return null;

  return createPortal(
    <div className="fixed top-11 left-52 right-0 bottom-0 z-[70] flex items-center justify-center">
      <div
        className="modal-backdrop absolute inset-0 bg-[#2e2522]/55 backdrop-blur-sm"
        onClick={onCancel}
      />
      <div className="modal-panel relative w-full max-w-sm mx-4 p-6 rounded-2xl bg-[#faf5ef] border border-[#dfcdbf] shadow-2xl">
        {/* Icon + Title */}
        <div className="flex items-start gap-3 mb-4">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
            destructive ? "bg-red-500/10" : "bg-[#b58a73]/10"
          }`}>
            <AlertTriangle size={18} className={destructive ? "text-red-500" : "text-[#b58a73]"} />
          </div>
          <div>
            <h3 className="text-sm font-medium text-[#2e2522] lowercase">{title}</h3>
            <p className="text-xs text-[#8a7a72] mt-1 lowercase leading-relaxed">{message}</p>
          </div>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-[#8a7a72] hover:text-[#2e2522] rounded-lg border border-[#dfcdbf] hover:border-[#c5b5a5] transition-colors lowercase"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium rounded-lg lowercase transition-colors ${
              destructive
                ? "bg-red-500/90 text-white hover:bg-red-600"
                : "bg-[#b58a73] text-black hover:bg-[#ff8c3a]"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}
