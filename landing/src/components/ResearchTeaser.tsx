import Link from "next/link";
import { ARTICLE } from "@/lib/evidence";

export function ResearchTeaser() {
  return (
    <section className="border-b border-[var(--line)] py-24 md:py-36">
      <div className="mx-auto grid w-full max-w-[1240px] gap-14 px-5 sm:px-8 md:grid-cols-[0.72fr_1.28fr] md:gap-20">
        <div>
          <p className="eyebrow text-[var(--gold)]">Field note · 01</p>
          <p className="mt-5 font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--fg-mute)]">
            {ARTICLE.published} · {ARTICLE.readingTime}
          </p>
        </div>
        <div>
          <blockquote className="max-w-[840px] font-serif text-[clamp(1.6rem,2.9vw,2.4rem)] leading-[1.22] tracking-[-0.022em] text-[var(--fg-strong)]">
            “Two embedding models, same vector width. Postgres compared them
            happily and returned noise. No error. Just wrong answers that
            looked fine.”
          </blockquote>
          <p className="mt-9 max-w-[690px] text-[17px] leading-8 text-[var(--fg-dim)]">
            {ARTICLE.dek}
          </p>
          <Link
            className="button-secondary mt-8"
            href={ARTICLE.href}
          >
            Read {ARTICLE.title} <span className="ml-3">→</span>
          </Link>
        </div>
      </div>
    </section>
  );
}
