"use client";

import { useState } from "react";

const COMMAND = "npx @synsci/delphi";

export function InstallChip({ className = "" }: { className?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      className={`install-chip ${className}`}
      onClick={() => {
        navigator.clipboard?.writeText(COMMAND).catch(() => {});
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      }}
      type="button"
    >
      <span aria-hidden="true">$</span>
      <code>{COMMAND}</code>
      <small>{copied ? "Copied" : "Copy"}</small>
    </button>
  );
}
