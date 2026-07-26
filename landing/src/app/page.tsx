import { Nav } from "@/components/Nav";
import { Hero } from "@/components/Hero";
import { HeroImage, ClosingImage } from "@/components/HeroImage";
import { WhatIs } from "@/components/WhatIs";
import { Benchmarks } from "@/components/Benchmarks";
import { HowItWorks } from "@/components/HowItWorks";
import { Quickstart } from "@/components/Quickstart";
import { OpenSource } from "@/components/OpenSource";
import { Footer } from "@/components/Footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <HeroImage variant="sacred-way" />
        <Hero />
        <WhatIs />
        <Benchmarks />
        <HowItWorks />
        <Quickstart />
        <OpenSource />
        <ClosingImage variant="archive" />
      </main>
      <Footer />
    </>
  );
}
