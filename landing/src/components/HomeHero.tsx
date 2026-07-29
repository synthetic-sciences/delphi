import Link from "next/link";
import { BENCHMARK, RETRIEVAL_COMPARISON } from "@/lib/evidence";

const DELPHI = RETRIEVAL_COMPARISON.find((row) => row.ours)!;
import { SiteNav } from "./SiteNav";
import { ThemedImage } from "./HeroImage";

export function HomeHero() {
  return (
    <section className="relative min-h-[100svh] overflow-hidden bg-[#070605] text-[#f7f0dc]">
      <ThemedImage variant="sacred-way" priority />
      <div className="hero-veil absolute inset-0" />
      <SiteNav mode="overlay" />

      <div className="relative z-10 mx-auto flex min-h-[100svh] w-full max-w-[1240px] items-end px-5 pb-12 pt-32 sm:px-8 md:pb-16">
        <div className="w-full">
          <div className="mb-8 flex items-center justify-between gap-8 border-b border-white/18 pb-4 font-mono text-[9px] uppercase tracking-[0.18em] text-[#d8cdb3]">
            <span>Open-source context infrastructure</span>
            <span className="hidden text-right sm:block">
              Code · Documentation · Papers · Datasets
            </span>
          </div>

          <h1 className="display-title max-w-[1110px] text-[#fff8e8]">
            The context engine for agents that have to get the code right.
          </h1>

          <div className="mt-9 grid gap-8 md:grid-cols-[minmax(0,620px)_1fr] md:items-end">
            <div>
              <p className="max-w-[590px] text-[17px] leading-7 text-[#e0d5bd] md:text-[19px] md:leading-8">
                Delphi indexes, retrieves, and assembles the evidence an agent
                needs to work across real software and research—locally, with
                provenance, under your control.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link
                  className="button-primary bg-[#fff8e8] text-[#090807]"
                  href="#install"
                >
                  Install Delphi <span className="ml-3">→</span>
                </Link>
                <Link
                  className="button-secondary border-white/30 text-[#f7f0dc] hover:border-[#bd9555]"
                  href="/blog/context-engine-is-the-product"
                >
                  Read the field note
                </Link>
              </div>
            </div>

            <div className="border-l border-white/20 pl-5 md:justify-self-end md:pl-7">
              <p className="font-serif text-[42px] leading-none tracking-[-0.04em] text-[#fff8e8]">
                {DELPHI.recall20.toFixed(3)}
              </p>
              <p className="mt-2 max-w-[270px] font-mono text-[9px] uppercase leading-5 tracking-[0.16em] text-[#cfc3aa]">
                recall@20 · {BENCHMARK.name} ·{" "}
                {BENCHMARK.cases} cases · 12.7x faster than the hosted comparator
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
