import { ARTICLE } from "@/lib/evidence";

export function ArticleHeader() {
  return (
    <header className="border-b border-[var(--line)] pb-16 pt-16 md:pb-24 md:pt-24">
      <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[9px] uppercase tracking-[0.16em] text-[var(--fg-mute)]">
          <span>Field note · 01</span>
          <span aria-hidden="true" className="text-[var(--line-strong)]">
            /
          </span>
          <time dateTime={ARTICLE.publishedIso}>{ARTICLE.published}</time>
          <span aria-hidden="true" className="text-[var(--line-strong)]">
            /
          </span>
          <span>{ARTICLE.readingTime}</span>
        </div>

        <h1 className="mt-10 max-w-[1120px] font-serif text-[clamp(4rem,10vw,9.4rem)] leading-[0.84] tracking-[-0.065em] text-[var(--fg-strong)]">
          {ARTICLE.title}
        </h1>

        <div className="mt-12 grid gap-10 border-t border-[var(--line-strong)] pt-7 md:grid-cols-[1.4fr_0.6fr] md:gap-20">
          <p className="max-w-[820px] text-[20px] leading-8 text-[var(--fg-dim)] md:text-[24px] md:leading-9">
            {ARTICLE.dek}
          </p>
          <div className="md:text-right">
            <p className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--fg-mute)]">
              By Synthetic Sciences
            </p>
            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 md:justify-end">
              {ARTICLE.labels.map((label) => (
                <span
                  className="font-mono text-[9px] uppercase tracking-[0.12em] text-[var(--gold)]"
                  key={label}
                >
                  {label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
