import Link from "next/link";
import { ClosingImage } from "@/components/HeroImage";
import { ContextPipeline } from "@/components/ContextPipeline";
import { HomeHero } from "@/components/HomeHero";
import { OpenSourceInstall } from "@/components/OpenSourceInstall";
import { ProductCapabilities } from "@/components/ProductCapabilities";
import { ResearchTeaser } from "@/components/ResearchTeaser";
import { ResultsSpread } from "@/components/ResultsSpread";
import { SiteFooter } from "@/components/SiteFooter";

export default function Home() {
  return (
    <>
      <main>
        <HomeHero />
        <ProductCapabilities />
        <ContextPipeline />
        <ResultsSpread />
        <OpenSourceInstall />
        <ResearchTeaser />
        <ClosingImage variant="archive">
          <div className="w-full">
            <p className="eyebrow text-[#bd9555]">Delphi · Synthetic Sciences</p>
            <div className="mt-5 grid gap-8 md:grid-cols-[1.15fr_0.85fr] md:items-end">
              {/* Was clamp(2.3rem,4.6vw,3.9rem), which rendered at 62px and
                  ran three lines across the middle of the archive plate. */}
              <h2 className="max-w-[24ch] font-serif text-[clamp(1.9rem,3.2vw,2.9rem)] leading-[1.06] tracking-[-0.03em] text-[#fff8e8]">
                Give the agent the evidence. Keep the record.
              </h2>
              <div className="flex flex-wrap gap-3 md:justify-end">
                <Link
                  className="button-primary bg-[#fff8e8] text-[#090807]"
                  href="#install"
                >
                  Get started
                </Link>
                <Link
                  className="button-secondary border-white/30 text-[#f7f0dc]"
                  href="/blog"
                >
                  Research blog
                </Link>
              </div>
            </div>
          </div>
        </ClosingImage>
      </main>
      <SiteFooter />
    </>
  );
}
