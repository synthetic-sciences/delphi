import Link from "next/link";
import {
  BENCHMARK,
  HEAD_TO_HEAD,
  HELD_OUT,
  RETRIEVAL_COMPARISON,
} from "@/lib/evidence";
import { ComparisonFigure, AblationFigure } from "./EvidenceFigure";

const DELPHI = RETRIEVAL_COMPARISON.find((row) => row.ours)!;
const RIVALS = RETRIEVAL_COMPARISON.filter((row) => !row.ours);
const bestRival = (key: "mrr" | "recall5") =>
  Math.max(...RIVALS.map((row) => row[key]));

const MEASUREMENTS = [
  {
    value: HEAD_TO_HEAD.delphi.recall20.toFixed(3),
    label: "Recall@20",
    detail: `${HEAD_TO_HEAD.cases} shared cases · comparator ${HEAD_TO_HEAD.nia.recall20.toFixed(3)}`,
    lead: true,
  },
  {
    value: `${HEAD_TO_HEAD.latencyRatio.toFixed(1)}x`,
    label: "Lower query latency",
    detail: `${(HEAD_TO_HEAD.delphi.latencyMs / 1000).toFixed(1)}s vs ${(HEAD_TO_HEAD.nia.latencyMs / 1000).toFixed(0)}s`,
    lead: true,
  },
  {
    value: `${(HELD_OUT.latencyMsMean / 1000).toFixed(2)} s`,
    label: "Mean query latency",
    detail: "held-out split, reranking on",
    lead: false,
  },
  {
    value: `${HELD_OUT.scored}`,
    label: "Held-out cases",
    detail: `${HELD_OUT.failures} failed queries`,
    lead: false,
  },
] as const;

export function ResultsSpread() {
  return (
    <section id="results" className="border-b border-[var(--line)] py-24 md:py-36">
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="grid gap-12 md:grid-cols-[0.72fr_1.28fr] md:gap-20">
          <div>
            <p className="eyebrow text-[var(--gold)]">Repository retrieval</p>
            <h2 className="section-title mt-5 text-[var(--fg-strong)]">
              Measured against the published baselines.
            </h2>
          </div>
          <div className="max-w-[680px] md:pt-9">
            <p className="text-[17px] leading-7 text-[var(--fg-dim)] md:text-[18px] md:leading-8">
              {BENCHMARK.cases} cases from {BENCHMARK.name}, scored by the
              benchmark&apos;s own code. Delphi beats every published baseline
              on MRR and Recall@5, and beats the hosted comparator on coverage
              at {HEAD_TO_HEAD.latencyRatio.toFixed(1)}x lower latency. The
              comparator still ranks the top of the list better.
            </p>
            <Link
              href="/blog/context-engine-is-the-product"
              className="mt-7 inline-block font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--gold)] underline decoration-[var(--line-strong)] underline-offset-8 hover:decoration-[var(--gold)]"
            >
              Read methods, ablations, and traces →
            </Link>
          </div>
        </div>

        <div className="mt-20 grid border-y border-[var(--line-strong)] md:grid-cols-4">
          {MEASUREMENTS.map((measurement, index) => (
            <div
              className={`py-7 md:min-h-[210px] md:px-6 md:py-9 ${
                index > 0
                  ? "border-t border-[var(--line)] md:border-l md:border-t-0"
                  : ""
              }`}
              key={measurement.label}
            >
              <p
                className={`font-serif text-[clamp(2.1rem,4vw,3.3rem)] leading-none tracking-[-0.035em] ${
                  measurement.lead
                    ? "text-[var(--gold)]"
                    : "text-[var(--fg-strong)]"
                }`}
              >
                {measurement.value}
              </p>
              <p className="mt-6 text-[15px] text-[var(--fg)]">
                {measurement.label}
              </p>
              <p className="mt-1 font-mono text-[9px] uppercase leading-5 tracking-[0.12em] text-[var(--fg-mute)]">
                {measurement.detail}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-20 grid gap-14 lg:grid-cols-2 lg:gap-20">
          <ComparisonFigure />
          <AblationFigure />
        </div>

        <div className="mt-14 grid gap-8 border-t border-[var(--line)] pt-8 text-[14px] leading-7 text-[var(--fg-mute)] md:grid-cols-2">
          <p>
            Delphi does not lead everywhere. The hosted comparator reaches{" "}
            {HEAD_TO_HEAD.nia.mrr.toFixed(3)} MRR against{" "}
            {DELPHI.mrr.toFixed(3)}, and grep still holds Recall@20.
          </p>
          <p>
            Held out: {HELD_OUT.scored} cases, {HELD_OUT.failures} failures,{" "}
            {HELD_OUT.mrr.toFixed(3)} MRR, ahead of the split it was tuned on.
          </p>
        </div>
      </div>
    </section>
  );
}
