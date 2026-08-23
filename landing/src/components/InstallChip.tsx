"use client";

import { useState } from "react";

const COMMAND = "npx @synsci/delphi";

export function InstallChip({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      aria-label={`Copy install command: ${COMMAND}`}
      className={`install-chip ${className}`}
      onClick={() => {
        navigator.clipboard?.writeText(COMMAND).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
      type="button"
    >
      <span aria-hidden="true" className="install-prompt">
        $
      </span>
      {COMMAND}
      <span aria-hidden="true" className="install-copy-icon">
        {copied ? (
          <svg fill="none" height="13" viewBox="0 0 13 13" width="13">
            <path d="M2.5 7 5 9.5 10.5 3.5" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        ) : (
          <svg fill="none" height="13" viewBox="0 0 13 13" width="13">
            <rect height="7" stroke="currentColor" width="7" x="4" y="4" />
            <path d="M9 4V2H2v7h2" fill="none" stroke="currentColor" />
          </svg>
        )}
      </span>
    </button>
  );
}
