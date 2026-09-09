"use client";

import { useState } from "react";

type Item = { key: string; label: string; command: string; dim?: string; note: string };

const INSTALL: Item[] = [
  {
    key: "npx",
    label: "npx",
    command: "npx @synsci/delphi",
    note: "Starts the local stack and registers Delphi with Claude Code, Cursor, Windsurf, or Claude Desktop. Needs Docker and Git; the default embeddings model runs locally, so no API key is required.",
  },
  {
    key: "proxy",
    label: "MCP proxy",
    command: "uvx synsci-delphi-proxy",
    note: "Connects any other MCP client to a running Delphi over stdio. Set SYNSC_API_KEY from the dashboard and SYNSC_API_URL to http://localhost:8742.",
  },
  {
    key: "source",
    label: "from source",
    command: "git clone https://github.com/synthetic-sciences/delphi",
    dim: " && cd delphi && ./scripts/launch_app.sh",
    note: "Runs the API, workers, PostgreSQL, and dashboard from a checkout. Copy env.example to .env first to change providers or ports.",
  },
];

function useCopy(text: string) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      return; // clipboard unavailable; the command is selectable text
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return { copied, copy };
}

function CopyStatus({ copied }: { copied: boolean }) {
  return (
    <span className="copy-status" aria-live="polite">
      {copied ? (
        <>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="square" />
          </svg>
          <span className="sr-only">Copied</span>
        </>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <rect x="8" y="8" width="11" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M5.5 15.5V6.5a1 1 0 0 1 1-1h9" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      )}
    </span>
  );
}

function Command({ item }: { item: Item }) {
  const full = `${item.command}${item.dim ?? ""}`;
  const { copied, copy } = useCopy(full);
  return (
    <button type="button" className="command" onClick={copy} aria-label={`Copy: ${full}`}>
      <span className="prompt" aria-hidden="true">
        $
      </span>
      <span className="command-script">
        {item.command}
        {item.dim ? <span className="dim">{item.dim}</span> : null}
      </span>
      <CopyStatus copied={copied} />
    </button>
  );
}

export function Install() {
  const [active, setActive] = useState(INSTALL[0].key);
  const item = INSTALL.find((entry) => entry.key === active) ?? INSTALL[0];
  return (
    <div className="install" id="install">
      <div role="tablist" aria-orientation="horizontal" aria-label="Install options" className="tablist">
        {INSTALL.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            id={`install-tab-${entry.key}`}
            aria-selected={entry.key === active}
            aria-controls="install-panel"
            className="tab"
            tabIndex={entry.key === active ? 0 : -1}
            onClick={() => setActive(entry.key)}
            onKeyDown={(event) => {
              const index = INSTALL.findIndex((candidate) => candidate.key === active);
              if (event.key === "ArrowRight") setActive(INSTALL[(index + 1) % INSTALL.length].key);
              if (event.key === "ArrowLeft") setActive(INSTALL[(index - 1 + INSTALL.length) % INSTALL.length].key);
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>
      <div id="install-panel" role="tabpanel" aria-labelledby={`install-tab-${item.key}`}>
        <Command item={item} />
        <p className="note">{item.note}</p>
      </div>
    </div>
  );
}
