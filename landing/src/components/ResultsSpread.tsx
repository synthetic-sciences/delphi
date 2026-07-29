import Link from "next/link";
import {
  DEVELOPER_PILOT,
  RETRIEVAL_AUDIT,
} from "@/lib/evidence";
import {
  CorpusAuditFigure,
  OutcomeFigure,
} from "./EvidenceFigure";

const MEASUREMENTS = [
  {
    value: `${DEVELOPER_PILOT.delphiPassAtOne.toFixed(1)}%`,
    label: "Delphi downstream pass@1",
    detail: "fixed-model developer pilot",
  },
  {
    value: `${DEVELOPER_PILOT.nextBestPassAtOne.toFixed(1)}%`,
    label: "Next-best tested condition",
    detail: "same model, same 40 tasks",
  },
  {
    value: `${RETRIEVAL_AUDIT.delphiLatencySeconds.toFixed(2)} s`,
    label: "Mean query latency",
    detail: "18 strict-valid repository cases",
  },
  {
    value: `${RETRIEVAL_AUDIT.latencyRatio.toFixed(1)}×`,
    label: "Lower observed latency",
    detail: "against the hosted comparator",
  },
] as const;

export function ResultsSpread() {
  return (
    <section id="results" className="border-b border-[var(--line)] py-24 md:py-36">
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="grid gap-12 md:grid-cols-[0.72fr_1.28fr] md:gap-20">
          <div>
            <p className="eyebrow text-[var(--gold)]">Measured downstream</p>
            <h2 className="section-title mt-5 text-[var(--fg-strong)]">
              Better context changed the answer.
            </h2>
          </div>
          <div className="max-w-[680px] md:pt-9">
            <p className="text-[20px] leading-8 text-[var(--fg-dim)] md:text-[23px] md:leading-9">
              With the model held fixed, Delphi produced the strongest code
              outcome in our 40-task developer pilot. The claim is narrow by
              design: state of the art in the tested developer-work setting,
              not everywhere context can be measured.
            </p>
            <Link
              href="/blog/context-engine-is-the-product"
              className="mt-7 inline-block font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--gold)] underline decoration-[var(--line-strong)] underline-offset-8 hover:decoration-[var(--gold)]"
            >
              Read methods and limitations →
            </Link>
          </div>
        </div>

        <div className="mt-20 grid border-y border-[var(--line-strong)] md:grid-cols-4">
          {MEASUREMENTS.map((measurement, index) => (
            <div
              className={`py-7 md:min-h-[230px] md:px-6 md:py-9 ${
                index > 0
                  ? "border-t border-[var(--line)] md:border-l md:border-t-0"
                  : ""
              }`}
              key={measurement.label}
            >
              <p
                className={`font-serif text-[clamp(3.2rem,6vw,5.8rem)] leading-none tracking-[-0.055em] ${
                  index === 0
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
          <OutcomeFigure />
          <CorpusAuditFigure />
        </div>

        <div className="mt-14 grid gap-8 border-t border-[var(--line)] pt-8 text-[14px] leading-7 text-[var(--fg-mute)] md:grid-cols-2">
          <p>
            The developer result uses Claude Opus 5 across every condition and
            reports descriptive pass@1. The 40-task slice is useful evidence,
            not a substitute for a larger held-out evaluation.
          </p>
          <p>
            The hosted comparator led MRR, recall@5, recall@10, and budgeted
            context yield on the strict-valid retrieval subset. Delphi&apos;s
            early ranking is an open problem, not a result we hide.
          </p>
        </div>
      </div>
    </section>
  );
}
