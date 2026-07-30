import { DOWNSTREAM, HEAD_TO_HEAD, INTERVALS } from "@/lib/evidence";

const RECALL20 = INTERVALS.find((row) => row.metric === "Recall@20")!;

/* The claim we can defend, and the one we cannot. This block used to say
 * Delphi was state of the art on the strength of a 40-task DS-1000 pilot.
 * That pilot is a null result at 100 tasks, and the hosted comparator leads
 * MRR, so the claim went with the evidence. */
export function ScopeStatement() {
  return (
    <aside className="my-12 border-y border-[var(--gold)] bg-[var(--gold-soft)] px-5 py-7 sm:px-7">
      <p className="eyebrow text-[var(--gold)]">What we can claim</p>
      <p className="mt-4 font-serif text-[22px] leading-8 text-[var(--fg-strong)] sm:text-[25px] sm:leading-9">
        Delphi finds more of the answer set than the hosted comparator, by{" "}
        {RECALL20.diff.toFixed(3)} Recall@20 with a 95% interval that clears
        zero, and returns it {HEAD_TO_HEAD.latencyRatio.toFixed(1)}x faster on
        your own hardware.
      </p>
      <p className="mt-4 text-[14px] leading-7 text-[var(--fg-mute)]">
        That is the only difference between the two that the sample can
        resolve. MRR and Recall@5 both sit inside intervals that span a win and
        a loss, so we are claiming neither. grep still leads Recall@20 among
        the published baselines, and on {DOWNSTREAM.tasks}{" "}
        {DOWNSTREAM.benchmark} tasks retrieval made no measurable difference to
        whether the generated code ran.
      </p>
    </aside>
  );
}
