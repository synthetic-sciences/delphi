import { PIPELINE, RETRIEVAL_AUDIT } from "@/lib/evidence";

export function OutcomeFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Downstream code correctness</span>
        <span>pass@1 · higher is better</span>
      </div>
      <div className="space-y-7 py-7">
        <BarRow label="Delphi" value="95.0%" width="95%" emphasis />
        <BarRow
          label="Next-best tested condition"
          value="90.0%"
          width="90%"
        />
      </div>
      <figcaption>
        Fixed Claude Opus 5 across a 40-task DS-1000 development pilot.
        Descriptive result; not a universal context-engine ranking.
      </figcaption>
    </figure>
  );
}

export function CorpusAuditFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Corpus-fidelity audit</span>
        <span>75 attempted cases</span>
      </div>
      <div
        className="audit-grid"
        role="img"
        aria-label="Of 75 attempted retrieval cases, 57 had truncated scored target files and 18 were strict-valid"
      >
        {Array.from({ length: RETRIEVAL_AUDIT.attempted }, (_, index) => (
          <span
            className={
              index < RETRIEVAL_AUDIT.excludedTruncated
                ? "audit-cell audit-cell-excluded"
                : "audit-cell audit-cell-valid"
            }
            key={index}
          />
        ))}
      </div>
      <div className="grid gap-4 border-t border-[var(--line)] py-5 sm:grid-cols-2">
        <MetricLabel
          value="57"
          label="excluded · scored target truncated"
        />
        <MetricLabel value="18" label="strict-valid · used for comparison" />
      </div>
      <figcaption>
        We report retrieval comparisons only where the scored target exists in
        both indexed corpora.
      </figcaption>
    </figure>
  );
}

export function RetrievalFigure() {
  const rows = [
    [
      "MRR",
      RETRIEVAL_AUDIT.delphiMrr,
      RETRIEVAL_AUDIT.comparatorMrr,
    ],
    [
      "Recall@5",
      RETRIEVAL_AUDIT.delphiRecall5,
      RETRIEVAL_AUDIT.comparatorRecall5,
    ],
    [
      "Recall@10",
      RETRIEVAL_AUDIT.delphiRecall10,
      RETRIEVAL_AUDIT.comparatorRecall10,
    ],
    [
      "Recall@20",
      RETRIEVAL_AUDIT.delphiRecall20,
      RETRIEVAL_AUDIT.comparatorRecall20,
    ],
  ] as const;

  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Strict-valid repository retrieval</span>
        <span>18 cases · higher is better</span>
      </div>
      <div className="divide-y divide-[var(--line)]">
        <div className="grid grid-cols-[1fr_72px_90px] gap-3 py-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
          <span>Metric</span>
          <span className="text-right">Delphi</span>
          <span className="text-right">Hosted comparator</span>
        </div>
        {rows.map(([label, delphi, comparator]) => (
          <div
            className="grid grid-cols-[1fr_72px_90px] gap-3 py-4 text-[14px]"
            key={label}
          >
            <span>{label}</span>
            <span
              className={`text-right font-mono ${
                delphi > comparator
                  ? "text-[var(--gold)]"
                  : "text-[var(--fg-dim)]"
              }`}
            >
              {delphi.toFixed(3)}
            </span>
            <span
              className={`text-right font-mono ${
                comparator > delphi
                  ? "text-[var(--fg-strong)]"
                  : "text-[var(--fg-mute)]"
              }`}
            >
              {comparator.toFixed(3)}
            </span>
          </div>
        ))}
      </div>
      <figcaption>
        The comparator leads early ranking. Delphi&apos;s recall@20 point
        estimate is higher, but the paired interval{" "}
        {RETRIEVAL_AUDIT.recall20Ci} crosses zero.
      </figcaption>
    </figure>
  );
}

export function LatencyFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Mean query latency</span>
        <span>seconds · lower is better</span>
      </div>
      <div className="space-y-7 py-7">
        <BarRow
          label="Delphi"
          value="1.25 s"
          width="4.7%"
          emphasis
        />
        <BarRow
          label="Hosted comparator"
          value="26.58 s"
          width="100%"
        />
      </div>
      <figcaption>
        Delphi was 21.3× lower-latency on the 18 strict-valid repository
        cases. Timing includes the observed query path, not indexing.
      </figcaption>
    </figure>
  );
}

export function PipelineFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>A context engine is a pipeline</span>
        <span>source → verified work</span>
      </div>
      <div className="pipeline-figure">
        {PIPELINE.map(([number, title, body]) => (
          <div className="pipeline-node" key={number}>
            <span>{number}</span>
            <strong>{title}</strong>
            <p>{body}</p>
          </div>
        ))}
      </div>
      <figcaption>
        A retrieval score observes one stage. The agent experiences the whole
        chain.
      </figcaption>
    </figure>
  );
}

function BarRow({
  label,
  value,
  width,
  emphasis = false,
}: {
  label: string;
  value: string;
  width: string;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <span className="text-[14px] text-[var(--fg-dim)]">{label}</span>
        <strong
          className={`font-mono text-[15px] ${
            emphasis ? "text-[var(--gold)]" : "text-[var(--fg-strong)]"
          }`}
        >
          {value}
        </strong>
      </div>
      <div className="h-[3px] bg-[var(--line)]">
        <div
          className={`h-full ${
            emphasis ? "bg-[var(--gold)]" : "bg-[var(--fg-mute)]"
          }`}
          style={{ width }}
        />
      </div>
    </div>
  );
}

function MetricLabel({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  return (
    <p className="flex items-baseline gap-3">
      <strong className="font-serif text-[36px] text-[var(--fg-strong)]">
        {value}
      </strong>
      <span className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
        {label}
      </span>
    </p>
  );
}

