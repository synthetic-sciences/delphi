import type { Metadata } from "next";
import Link from "next/link";
import { ARTICLE } from "@/lib/evidence";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteNav } from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "Research blog · Delphi",
  description:
    "Field notes from Delphi on context engines, retrieval, evaluation, and developer agents.",
  alternates: {
    canonical: "https://trydelphi.ai/blog",
  },
  openGraph: {
    title: "Research blog · Delphi",
    description:
      "Field notes on context engines, retrieval, evaluation, and developer agents.",
    url: "https://trydelphi.ai/blog",
  },
};

export default function BlogIndex() {
  return (
    <>
      <SiteNav />
      <main>
        <header className="border-b border-[var(--line)] py-20 md:py-32">
          <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
            <p className="eyebrow text-[var(--gold)]">
              Delphi research · field notes
            </p>
            <h1 className="mt-6 max-w-[1050px] font-serif text-[clamp(4rem,10vw,9.8rem)] leading-[0.84] tracking-[-0.065em] text-[var(--fg-strong)]">
              Work from the context layer.
            </h1>
            <p className="mt-10 max-w-[660px] text-[19px] leading-8 text-[var(--fg-dim)]">
              Experiments, failures, and engineering notes from building
              context infrastructure for agents that have to finish real work.
            </p>
          </div>
        </header>

        <section className="py-20 md:py-28">
          <div className="mx-auto w-full max-w-[1240px] px-5 sm:px-8">
            <article className="grid gap-8 border-y border-[var(--line-strong)] py-8 md:grid-cols-[120px_1fr_220px] md:gap-12 md:py-12">
              <div>
                <p className="font-mono text-[10px] text-[var(--gold)]">01</p>
                <p className="mt-3 font-mono text-[9px] uppercase leading-5 tracking-[0.14em] text-[var(--fg-mute)]">
                  <time dateTime={ARTICLE.publishedIso}>{ARTICLE.published}</time>
                  <br />
                  {ARTICLE.readingTime}
                </p>
              </div>

              <div>
                <h2 className="max-w-[760px] font-serif text-[clamp(2.8rem,5vw,5.5rem)] leading-[0.95] tracking-[-0.05em] text-[var(--fg-strong)]">
                  <Link
                    className="transition-colors hover:text-[var(--gold)]"
                    href={ARTICLE.href}
                  >
                    {ARTICLE.title}
                  </Link>
                </h2>
                <p className="mt-7 max-w-[710px] text-[16px] leading-8 text-[var(--fg-dim)]">
                  {ARTICLE.dek}
                </p>
                <Link
                  className="mt-7 inline-block font-mono text-[10px] uppercase tracking-[0.15em] text-[var(--gold)]"
                  href={ARTICLE.href}
                >
                  Read field note →
                </Link>
              </div>

              <div className="flex flex-wrap content-start gap-x-4 gap-y-2 border-t border-[var(--line)] pt-5 md:border-l md:border-t-0 md:pl-7 md:pt-0">
                {ARTICLE.labels.map((label) => (
                  <span
                    className="font-mono text-[9px] uppercase tracking-[0.13em] text-[var(--fg-mute)]"
                    key={label}
                  >
                    {label}
                  </span>
                ))}
              </div>
            </article>
          </div>
        </section>
      </main>
      <SiteFooter />
    </>
  );
}

