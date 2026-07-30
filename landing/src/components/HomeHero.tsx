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
    <section className="relative flex min-h-[100svh] flex-col overflow-hidden bg-[#070605] text-[#f7f0dc]">
      <div className="hero-plate">
        <ThemedImage variant="sacred-way" priority fit="natural" />
      </div>
      <div className="hero-scrim" />
      <SiteNav mode="overlay" />

      {/* mt-auto pins the copy to the floor of the frame. The block is kept
          short on purpose: every line added here climbs back up into the
          engraving, which is the thing it must not do. */}
      <div className="relative z-10 mx-auto mt-auto w-full max-w-[1180px] px-5 pb-[8vh] sm:px-8">
        <p className="eyebrow text-[#bd9555]">Open source · Apache 2.0</p>

        <h1 className="hero-title mt-4 max-w-[24ch] text-[#fff8e8]">
          Give your coding agent the right files.
        </h1>

        <p className="mt-5 max-w-[50ch] text-[16px] leading-[1.6] text-[#ddd2ba] sm:text-[17px]">
          Delphi indexes your repositories, docs, and papers, then answers an
          agent&apos;s question with the exact code that answers it. Runs on
          your own machine.
        </p>

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <Link className="button-primary bg-[#fff8e8] text-[#090807]" href="#install">
            Install Delphi <span className="ml-3">→</span>
          </Link>
          <Link
            className="button-secondary border-white/30 text-[#f7f0dc] hover:border-[#bd9555]"
            href="#product"
          >
            See how it works
          </Link>
        </div>

        <p className="mt-8 border-t border-white/15 pt-4 font-mono text-[10px] uppercase leading-5 tracking-[0.14em] text-[#bdb29a]">
          {HEAD_TO_HEAD.delphi.recall20.toFixed(3)} recall@20 ·{" "}
          {HEAD_TO_HEAD.latencyRatio.toFixed(1)}× faster than the hosted
          comparator · {HEAD_TO_HEAD.cases} shared cases
        </p>
      </div>
    </section>
  );
}
