import Link from "next/link";
import { HEAD_TO_HEAD } from "@/lib/evidence";
import { SiteNav } from "./SiteNav";
import { ThemedImage } from "./HeroImage";

/* The engraving occupies the top of the frame and fades out before the copy
 * begins, so no headline is ever set over the busy part of the plate. The
 * scrim below it runs to solid background, which is what makes the type
 * legible without needing a text-shadow or a flat overlay across the whole
 * image — the artwork stays readable at the top, the words stay readable at
 * the bottom, and neither fights the other. */
export function HomeHero() {
  return (
    <section className="relative min-h-[100svh] overflow-hidden bg-[#070605] text-[#f7f0dc]">
      <div className="hero-plate">
        <ThemedImage variant="sacred-way" priority />
      </div>
      <div className="hero-scrim" />
      <SiteNav mode="overlay" />

      <div className="relative z-10 mx-auto flex min-h-[100svh] w-full max-w-[1180px] flex-col justify-end px-5 pb-14 pt-28 sm:px-8 md:pb-20">
        <p className="eyebrow text-[#bd9555]">Open-source context infrastructure</p>

        <h1 className="hero-title mt-5 max-w-[19ch] text-[#fff8e8]">
          The context engine for agents that write code.
        </h1>

        <p className="mt-6 max-w-[54ch] text-[16px] leading-[1.65] text-[#ddd2ba] sm:text-[17px]">
          Delphi indexes your code, docs, and papers, then hands an agent the
          evidence it needs. Runs locally. Every answer traceable.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link className="button-primary bg-[#fff8e8] text-[#090807]" href="#install">
            Install Delphi <span className="ml-3">→</span>
          </Link>
          <Link
            className="button-secondary border-white/30 text-[#f7f0dc] hover:border-[#bd9555]"
            href="/blog/context-engine-is-the-product"
          >
            Read the field note
          </Link>
        </div>

        <p className="mt-10 border-t border-white/15 pt-5 font-mono text-[10px] uppercase leading-5 tracking-[0.14em] text-[#bdb29a]">
          {HEAD_TO_HEAD.delphi.recall20.toFixed(3)} recall@20 ·{" "}
          {HEAD_TO_HEAD.latencyRatio.toFixed(1)}× faster than the hosted
          comparator · {HEAD_TO_HEAD.cases} shared cases
        </p>
      </div>
    </section>
  );
}
