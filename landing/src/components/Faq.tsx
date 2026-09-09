"use client";

import { useId, useState, type ReactNode } from "react";

export function Faq({ question, children }: { question: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="faq-item">
      <button
        type="button"
        className="faq-question"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? (
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M5 11.5H19V12.5H5Z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12.5 11.5H19V12.5H12.5V19H11.5V12.5H5V11.5H11.5V5H12.5V11.5Z" />
          </svg>
        )}
        <span className="faq-question-text">{question}</span>
      </button>
      {open ? (
        <div id={id} className="faq-answer">
          {children}
        </div>
      ) : null}
    </div>
  );
}
