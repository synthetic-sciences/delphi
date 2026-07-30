"use client";

import { useState } from "react";

/* Expandable evidence.
 *
 * Every number in the article should be openable down to the query that
 * produced it. These components render the run artifacts directly — the
 * ranked file list, which retrieval branch found each file, and the raw
 * JSON record — so a reader can check a claim instead of trusting it. */

export type RankedFile = {
  path: string;
  score: number;
  /** Retrieval branches that surfaced this file: vector, bm25, symbol. */
  branches?: string[];
};

export type RetrievalTrace = {
  sampleId: string;
  workflow: string;
  repo: string;
  query: string;
  goldFiles: string[];
  ranked: RankedFile[];
  latencyMs?: number;
  /** Anything else worth showing verbatim under "raw record". */
  raw?: unknown;
};

const BRANCH_LABEL: Record<string, string> = {
  vector: "vec",
  bm25: "bm25",
  symbol: "sym",
  path: "path",
  path_affinity: "path~",
  trigram: "tri",
};

function Disclosure({
  summary,
  meta,
  children,
  defaultOpen = false,
}: {
  summary: string;
  meta?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="trace-disclosure">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="trace-summary"
      >
        <span className="trace-caret" aria-hidden="true">
          {open ? "−" : "+"}
        </span>
        <span className="trace-summary-text">{summary}</span>
        {meta ? <span className="trace-summary-meta">{meta}</span> : null}
      </button>
      {open ? <div className="trace-body">{children}</div> : null}
    </div>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="trace-json">
      <code>{JSON.stringify(value, null, 2)}</code>
    </pre>
  );
}

export function QueryTrace({
  trace,
  defaultOpen = false,
}: {
  trace: RetrievalTrace;
  defaultOpen?: boolean;
}) {
  const gold = new Set(trace.goldFiles);
  const hitRank = trace.ranked.findIndex((file) => gold.has(file.path)) + 1;

  return (
    <Disclosure
      summary={`${trace.workflow} · ${trace.repo}`}
      meta={hitRank > 0 ? `gold at rank ${hitRank}` : "gold not retrieved"}
      defaultOpen={defaultOpen}
    >
      <dl className="trace-facts">
        <dt>Sample</dt>
        <dd className="font-mono">{trace.sampleId}</dd>
        <dt>Gold</dt>
        <dd className="font-mono">{trace.goldFiles.join(", ")}</dd>
        {trace.latencyMs !== undefined ? (
          <>
            <dt>Latency</dt>
            <dd className="font-mono">{Math.round(trace.latencyMs)} ms</dd>
          </>
        ) : null}
      </dl>

      <Disclosure summary="Query sent to the engine">
        <pre className="trace-json">
          <code>{trace.query}</code>
        </pre>
      </Disclosure>

      <div className="trace-ranked">
        <div className="trace-ranked-head">
          <span>#</span>
          <span>file</span>
          <span>found by</span>
          <span>score</span>
        </div>
        {trace.ranked.map((file, index) => {
          const isGold = gold.has(file.path);
          return (
            <div
              key={`${file.path}-${index}`}
              className={`trace-ranked-row${isGold ? " is-gold" : ""}`}
            >
              <span className="font-mono">{index + 1}</span>
              <span className="font-mono trace-path">
                {file.path}
                {isGold ? <em aria-label="gold file"> ← gold</em> : null}
              </span>
              <span className="font-mono trace-branches">
                {(file.branches ?? [])
                  .map((branch) => BRANCH_LABEL[branch] ?? branch)
                  .join(" ") || "none"}
              </span>
              <span className="font-mono">{file.score.toFixed(3)}</span>
            </div>
          );
        })}
      </div>

      {trace.raw !== undefined ? (
        <Disclosure summary="Raw record">
          <JsonBlock value={trace.raw} />
        </Disclosure>
      ) : null}
    </Disclosure>
  );
}

export function EvidenceDisclosure({
  summary,
  meta,
  children,
}: {
  summary: string;
  meta?: string;
  children: React.ReactNode;
}) {
  return (
    <Disclosure summary={summary} meta={meta}>
      {children}
    </Disclosure>
  );
}
