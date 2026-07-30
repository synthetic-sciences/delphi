import {
  ABLATION,
  BENCHMARK,
  EMBEDDING_MISMATCH,
  PIPELINE,
  RERANKER_CHOICE,
  RETRIEVAL_COMPARISON,
} from "@/lib/evidence";

/* Figures read straight off the evidence module so a number can never drift
 * between the prose and the artifact it came from. */

export function ComparisonFigure() {
  const metrics = [
    { key: "mrr", label: "MRR" },
    { key: "recall5", label: "Recall@5" },
    { key: "recall20", label: "Recall@20" },
  ] as const;

  const best = Object.fromEntries(
    metrics.map(({ key }) => [
      key,
      Math.max(...RETRIEVAL_COMPARISON.map((row) => row[key])),
    ]),
  ) as Record<(typeof metrics)[number]["key"], number>;

  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Against published baselines</span>
        <span>
          {BENCHMARK.cases} cases · higher is better
        </span>
      </div>
      <div className="divide-y divide-[var(--line)]">
        <div className="grid grid-cols-[1fr_64px_64px_72px] gap-3 py-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
          <span>System</span>
          {metrics.map((metric) => (
            <span className="text-right" key={metric.key}>
              {metric.label}
            </span>
          ))}
        </div>
        {RETRIEVAL_COMPARISON.map((row) => (
          <div
            className="grid grid-cols-[1fr_64px_64px_72px] gap-3 py-4 text-[14px]"
            key={row.system}
          >
            <span className={row.ours ? "text-[var(--fg-strong)]" : undefined}>
              {row.system}
            </span>
            {metrics.map((metric) => (
              <span
                className={`text-right font-mono ${
                  row[metric.key] === best[metric.key]
                    ? "text-[var(--gold)]"
                    : "text-[var(--fg-mute)]"
                }`}
                key={metric.key}
              >
                {row[metric.key].toFixed(3)}
              </span>
            ))}
          </div>
        ))}
      </div>
      <figcaption>
        Baselines are the benchmark&apos;s own published runs on the same split
        and candidate filter, scored by the same code. Gold marks the leader in
        each column. grep still holds Recall@20.
      </figcaption>
    </figure>
  );
}

export function AblationFigure() {
  const peak = Math.max(...ABLATION.map((row) => row.recall20));

  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>What each change was worth</span>
        <span>same {BENCHMARK.cases} cases</span>
      </div>
      <div className="divide-y divide-[var(--line)]">
        {ABLATION.map((row) => (
          <div className="py-4" key={row.label}>
            <div className="flex items-baseline justify-between gap-4">
              <span className="text-[14px] text-[var(--fg)]">{row.label}</span>
              <span className="font-mono text-[13px] text-[var(--fg-strong)]">
                {row.recall20.toFixed(3)}
              </span>
            </div>
            <div
              className="mt-2 h-[3px] bg-[var(--gold)]"
              style={{ width: `${(row.recall20 / peak) * 100}%` }}
            />
            <p className="mt-2 font-mono text-[9px] uppercase leading-5 tracking-[0.12em] text-[var(--fg-mute)]">
              {row.note} · mrr {row.mrr.toFixed(3)} ·{" "}
              {(row.latencyMs / 1000).toFixed(1)}s
            </p>
          </div>
        ))}
      </div>
      <figcaption>
        Recall@20 by configuration. The first row is what the previous
        evaluation actually measured: a corpus indexed by one embedding model
        and queried by another.
      </figcaption>
    </figure>
  );
}

export function MismatchFigure() {
  const { cosineBefore, cosineAfter, dimension, repositoriesAffected } =
    EMBEDDING_MISMATCH;
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Self-retrieval check</span>
        <span>{dimension}-dim both sides</span>
      </div>
      <div className="grid gap-6 py-6 sm:grid-cols-2">
        {[
          { label: "Mismatched models", value: cosineBefore },
          { label: "Aligned models", value: cosineAfter },
        ].map((row) => (
          <div key={row.label}>
            <p className="measure text-[var(--fg-strong)]">
              {row.value.toFixed(3)}
            </p>
            <p className="mt-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
              {row.label}
            </p>
          </div>
        ))}
      </div>
      <figcaption>
        Cosine between a chunk&apos;s stored vector and a fresh embedding of
        that chunk&apos;s own exact content. A matched space returns ~1.0.
        Because both models emit {dimension}-dimensional vectors, pgvector
        accepted the comparison and {repositoriesAffected} repositories scored
        as noise without raising anything.
      </figcaption>
    </figure>
  );
}

export function RerankerFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Cross-encoder selection</span>
        <span>quality and latency together</span>
      </div>
      <div className="divide-y divide-[var(--line)]">
        <div className="grid grid-cols-[1fr_56px_64px_64px] gap-3 py-3 font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
          <span>Model</span>
          <span className="text-right">Params</span>
          <span className="text-right">MRR</span>
          <span className="text-right">Latency</span>
        </div>
        {RERANKER_CHOICE.map((row) => (
          <div
            className="grid grid-cols-[1fr_56px_64px_64px] gap-3 py-4 text-[14px]"
            key={row.model}
          >
            <span>{row.model}</span>
            <span className="text-right font-mono text-[var(--fg-mute)]">
              {row.params}
            </span>
            <span className="text-right font-mono text-[var(--fg-strong)]">
              {row.mrr.toFixed(3)}
            </span>
            <span className="text-right font-mono text-[var(--fg-mute)]">
              {(row.latencyMs / 1000).toFixed(1)}s
            </span>
          </div>
        ))}
      </div>
      <figcaption>
        The 22M-parameter model beats the 278M code-aware one on every metric
        while running roughly seven times faster, so the larger model cost
        latency and quality at once.
      </figcaption>
    </figure>
  );
}

export function PipelineFigure() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Context pipeline</span>
        <span>index → act</span>
      </div>
      <div className="pipeline-figure">
        {PIPELINE.map(([index, stage, detail]) => (
          <div className="pipeline-node" key={index}>
            <span>{index}</span>
            <strong>{stage}</strong>
            <p>{detail}</p>
          </div>
        ))}
      </div>
      <figcaption>
        Retrieval is one stage of five. A file found at rank 40 is not context.
      </figcaption>
    </figure>
  );
}
