import Link from "next/link";
import { ClosingImage } from "@/components/HeroImage";
import { ContextPipeline } from "@/components/ContextPipeline";
import { HomeHero } from "@/components/HomeHero";
import { OpenSourceInstall } from "@/components/OpenSourceInstall";
import { ProductTimeline } from "@/components/ProductTimeline";
import { ResearchTeaser } from "@/components/ResearchTeaser";
import { ResultsSpread } from "@/components/ResultsSpread";
import { SiteFooter } from "@/components/SiteFooter";

export default function Home() {
  return (
    <>
      <main>
        <HomeHero />
        <ResultsSpread />
        <ContextPipeline />
        <ProductTimeline />
        <OpenSourceInstall />
        <ResearchTeaser />
        <ClosingImage variant="archive">
          <div className="w-full">
            <p className="eyebrow text-[#bd9555]">Delphi · Synthetic Sciences</p>
            <div className="mt-5 grid gap-8 md:grid-cols-[1.25fr_0.75fr] md:items-end">
              <h2 className="max-w-[850px] font-serif text-[clamp(3.2rem,7vw,7.2rem)] leading-[0.9] tracking-[-0.055em] text-[#fff8e8]">
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
