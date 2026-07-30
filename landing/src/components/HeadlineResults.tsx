import { HEAD_TO_HEAD, INTERVALS } from "@/lib/evidence";

/* The table the piece opens on. Every row states the comparator, the shipped
 * build, and whether the sample can tell them apart, so a reader can see what
 * is claimed and what is not without reading the methods first. */

const ROWS = INTERVALS.map((interval) => {
  const key =
    interval.metric === "MRR"
      ? ("mrr" as const)
      : interval.metric === "Recall@5"
        ? ("recall5" as const)
        : interval.metric === "Recall@20"
          ? ("recall20" as const)
          : ("bcy8k" as const);
  return {
    metric: interval.metric,
    nia: HEAD_TO_HEAD.nia[key],
    delphi: HEAD_TO_HEAD.delphi[key],
    diff: interval.diff,
    lo: interval.lo,
    hi: interval.hi,
    resolved: interval.resolved,
  };
});

export function HeadlineResults() {
  return (
    <figure className="evidence-figure">
      <div className="figure-heading">
        <span>Shipped build against the hosted comparator</span>
        <span>
          {HEAD_TO_HEAD.cases} paired cases · 95% interval
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-[14px]">
          <thead>
            <tr className="border-b border-[var(--line-strong)] font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--fg-mute)]">
              <th className="py-3 text-left font-normal">Metric</th>
              <th className="py-3 text-right font-normal">{HEAD_TO_HEAD.comparator}</th>
              <th className="py-3 text-right font-normal">Delphi</th>
              <th className="py-3 text-right font-normal">Difference</th>
              <th className="py-3 text-right font-normal">Resolved</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((row) => (
              <tr className="border-b border-[var(--line)]" key={row.metric}>
                <td className="py-4 text-[var(--fg)]">{row.metric}</td>
                <td className="py-4 text-right font-mono text-[var(--fg-mute)]">
                  {row.nia.toFixed(3)}
                </td>
                <td
                  className={`py-4 text-right font-mono ${
                    row.resolved ? "text-[var(--gold)]" : "text-[var(--fg-strong)]"
                  }`}
                >
                  {row.delphi.toFixed(3)}
                </td>
                <td className="py-4 text-right font-mono text-[var(--fg-mute)]">
                  {row.diff > 0 ? "+" : ""}
                  {row.diff.toFixed(3)}{" "}
                  <span className="text-[11px]">
                    [{row.lo > 0 ? "+" : ""}
                    {row.lo.toFixed(3)}, {row.hi > 0 ? "+" : ""}
                    {row.hi.toFixed(3)}]
                  </span>
                </td>
                <td className="py-4 text-right font-mono text-[11px] uppercase tracking-[0.1em]">
                  <span
                    className={
                      row.resolved ? "text-[var(--gold)]" : "text-[var(--fg-mute)]"
                    }
                  >
                    {row.resolved ? "yes" : "no"}
                  </span>
                </td>
              </tr>
            ))}
            <tr>
              <td className="py-4 text-[var(--fg)]">Query latency</td>
              <td className="py-4 text-right font-mono text-[var(--fg-mute)]">
                {(HEAD_TO_HEAD.nia.latencyMs / 1000).toFixed(1)}s
              </td>
              <td className="py-4 text-right font-mono text-[var(--gold)]">
                {(HEAD_TO_HEAD.delphi.latencyMs / 1000).toFixed(1)}s
              </td>
              <td className="py-4 text-right font-mono text-[var(--fg-mute)]">
                {HEAD_TO_HEAD.latencyRatio.toFixed(1)}x faster
              </td>
              <td className="py-4 text-right font-mono text-[11px] uppercase tracking-[0.1em] text-[var(--gold)]">
                yes
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <figcaption>
        Paired per case over the {HEAD_TO_HEAD.cases}{" "}
        final-split cases the comparator completed without error, 4000
        bootstrap resamples. A
        difference counts only when its interval excludes zero, which here is
        Recall@20 and latency. Both engines indexed the same corpora and were
        scored by the benchmark&apos;s own code.
      </figcaption>
    </figure>
  );
}
