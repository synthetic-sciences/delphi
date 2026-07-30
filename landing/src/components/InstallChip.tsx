"use client";

import { useState } from "react";

const COMMAND = "npm i -g @synsci/delphi";

/* Click-to-copy install command, sat next to the hero buttons. The label
 * swaps to a tick for a moment on success and says nothing on failure, since
 * a clipboard permission prompt is not the visitor's problem to solve. */
export function InstallChip({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      aria-label={`Copy install command: ${COMMAND}`}
      className={`group inline-flex h-11 items-center gap-3 border border-white/20 bg-black/30 pl-4 pr-3 font-mono text-[12px] text-[#ddd2ba] backdrop-blur-[3px] transition-colors hover:border-white/40 hover:text-[#fff8e8] ${className}`}
      onClick={() => {
        navigator.clipboard?.writeText(COMMAND).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
      type="button"
    >
      <span aria-hidden="true" className="text-[#bd9555]">
        $
      </span>
      {COMMAND}
      <span aria-hidden="true" className="ml-1 text-white/45 group-hover:text-white/80">
        {copied ? (
          <svg fill="none" height="13" viewBox="0 0 13 13" width="13">
            <path d="M2.5 7 5 9.5 10.5 3.5" stroke="#bd9555" strokeWidth="1.4" />
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
