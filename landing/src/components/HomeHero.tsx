import Link from "next/link";
import { HEAD_TO_HEAD } from "@/lib/evidence";
import { InstallChip } from "./InstallChip";
import { SiteNav } from "./SiteNav";
import { ThemedImage } from "./HeroImage";

/* The plate runs full bleed and is never faded or cropped away: the engraving
 * is the page, not a backdrop for it. Legibility comes from darkening only the
 * two corners the type occupies, which leaves the temple and the Sacred Way
 * untouched in the middle. Wordmark top left, everything you can act on
 * gathered bottom right. */
export function HomeHero() {
  return (
    <section className="relative flex h-[100svh] min-h-[680px] w-full flex-col overflow-hidden bg-[var(--bg)] text-[#f7f0dc]">
      <div className="hero-plate">
        <ThemedImage variant="sacred-way" priority />
      </div>
      <div className="hero-grain" />
      <div className="hero-vignette" />
      <div className="hero-fade" />

      <SiteNav mode="overlay" showWordmark={false} />

      <div className="relative z-10 mx-auto flex h-full w-full max-w-[1400px] flex-col px-6 pb-[6vh] pt-[14vh] sm:px-10">
        <div>
          <p className="font-serif text-[clamp(44px,6.4vw,86px)] leading-[0.92] tracking-[-0.04em] text-[#fff8e8]">
            delphi
          </p>
          <Link
            className="mt-2 inline-block text-[clamp(12px,1.1vw,15px)] tracking-[0.03em] text-[#bdb29a] transition-colors hover:text-[#f7f0dc]"
            href="https://syntheticsciences.ai"
          >
            by Synthetic Sciences
          </Link>
        </div>

        <div className="mt-auto max-w-[820px] self-end text-right">
          <h1 className="hero-title text-[#fff8e8]">
            Give your coding agent the right files.
          </h1>

          <p className="ml-auto mt-6 max-w-[52ch] text-[16px] leading-[1.65] text-[#ddd2ba] sm:text-[17px]">
            Delphi indexes your repositories, docs, and papers, then answers an
            agent&apos;s question with the code that actually answers it. Runs
            on your own machine.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-end gap-3">
            <Link
              className="button-primary bg-[#fff8e8] text-[#090807]"
              href="#install"
            >
              Install Delphi <span className="ml-3">→</span>
            </Link>
            <Link
              className="button-secondary border-white/25 text-[#f7f0dc] hover:border-[#bd9555]"
              href="https://github.com/synthetic-sciences/delphi"
            >
              Star on GitHub
            </Link>
            <InstallChip className="hidden sm:inline-flex" />
          </div>

          <p className="ml-auto mt-8 max-w-[62ch] border-t border-white/15 pt-4 font-mono text-[10px] uppercase leading-5 tracking-[0.14em] text-[#bdb29a]">
            {HEAD_TO_HEAD.delphi.recall20.toFixed(3)} recall@20 ·{" "}
            {HEAD_TO_HEAD.latencyRatio.toFixed(1)}× faster than the hosted
            comparator · {HEAD_TO_HEAD.cases} shared cases
          </p>
        </div>
      </div>
    </section>
  );
}
