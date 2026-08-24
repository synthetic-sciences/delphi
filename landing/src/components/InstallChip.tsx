"use client";

import { useState } from "react";

const COMMAND = "npx @synsci/delphi";

export function InstallChip({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(COMMAND).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
      className={`group/chip inline-flex items-center gap-3 border border-border bg-background/45 backdrop-blur-[3px] pl-4 pr-3 h-11 font-terminal text-[13px] text-foreground/80 hover:border-foreground/35 hover:text-foreground transition-colors duration-300 cursor-pointer ${className}`}
      aria-label="Copy the install command"
    >
      <span className="text-foreground/40" aria-hidden>
        $
      </span>
      {COMMAND}
      <span
        className="ml-1 text-foreground/40 group-hover/chip:text-foreground/75 transition-colors"
        aria-hidden
      >
        {copied ? (
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <path d="M2.5 7 5 9.5 10.5 3.5" stroke="hsl(86 30% 60%)" strokeWidth="1.4" />
          </svg>
        ) : (
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <rect x="4" y="4" width="7" height="7" stroke="currentColor" />
            <path d="M9 4V2H2v7h2" stroke="currentColor" fill="none" />
          </svg>
        )}
      </span>
    </button>
  );
}
