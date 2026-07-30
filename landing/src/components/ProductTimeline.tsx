import { TIMELINE } from "@/lib/evidence";

export function ProductTimeline() {
  return (
    <section className="border-b border-[var(--line)] py-24 md:py-36">
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="grid gap-10 md:grid-cols-[0.65fr_1.35fr] md:gap-20">
          <div>
            <p className="eyebrow text-[var(--gold)]">Timeline</p>
            <h2 className="mt-5 max-w-[480px] font-serif text-[clamp(2.7rem,5vw,5rem)] leading-[0.98] tracking-[-0.045em] text-[var(--fg-strong)]">
              Context became infrastructure.
            </h2>
          </div>

          <ol className="border-t border-[var(--line-strong)]">
            {TIMELINE.map((entry, index) => (
              <li
                className="grid gap-4 border-b border-[var(--line)] py-7 sm:grid-cols-[110px_1fr] sm:gap-8"
                key={`${entry.date}-${entry.title}`}
              >
                <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--gold)]">
                  {entry.date}
                </p>
                <div>
                  <div className="flex items-baseline gap-4">
                    <span className="font-mono text-[9px] text-[var(--fg-mute)]">
                      0{index + 1}
                    </span>
                    <h3 className="font-serif text-[25px] tracking-[-0.02em] text-[var(--fg-strong)]">
                      {entry.title}
                    </h3>
                  </div>
                  <p className="mt-3 max-w-[620px] text-[14px] leading-7 text-[var(--fg-mute)]">
                    {entry.body}
                  </p>
                  {index === TIMELINE.length - 1 && (
                    <p className="mt-4 font-mono text-[9px] uppercase tracking-[0.13em] text-[var(--fg-dim)]">
                      Every number held out and re-measured before publishing.
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
