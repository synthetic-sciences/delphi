import { DOWNSTREAM, HEAD_TO_HEAD } from "@/lib/evidence";

/* The claim we can defend, and the one we cannot. This block used to say
 * Delphi was state of the art on the strength of a 40-task DS-1000 pilot.
 * That pilot is a null result at 100 tasks, and the hosted comparator leads
 * MRR, so the claim went with the evidence. */
export function ScopeStatement() {
  return (
    <aside className="my-12 border-y border-[var(--gold)] bg-[var(--gold-soft)] px-5 py-7 sm:px-7">
      <p className="eyebrow text-[var(--gold)]">What we can claim</p>
      <p className="mt-4 font-serif text-[22px] leading-8 text-[var(--fg-strong)] sm:text-[25px] sm:leading-9">
        Delphi finds more of the answer set than the hosted comparator and
        returns it {HEAD_TO_HEAD.latencyRatio.toFixed(1)}x faster, on your own
        hardware. It beats every published baseline on early precision.
      </p>
      <p className="mt-4 text-[14px] leading-7 text-[var(--fg-mute)]">
        We are not claiming state of the art. The comparator ranks the top of
        the list better, grep still leads Recall@20, and on {DOWNSTREAM.tasks}{" "}
        {DOWNSTREAM.benchmark} tasks retrieval made no measurable difference to
        whether the generated code ran.
      </p>
    </aside>
  );
}
