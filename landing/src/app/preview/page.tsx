import Image from "next/image";
import Link from "next/link";
import { Nav } from "@/components/Nav";

const VARIANTS = [
  {
    n: "01",
    key: "sacred-way",
    name: "The Sacred Way",
    blurb:
      "A lone scholar climbs the Sacred Way of Delphi, the Temple of Apollo silhouetted on Mount Parnassus.",
  },
  {
    n: "02",
    key: "pythia",
    name: "The Pythia",
    blurb:
      "The Pythia on her bronze tripod in the inner sanctum of the Temple of Apollo, vapours rising from the fissure below.",
  },
  {
    n: "03",
    key: "omphalos",
    name: "The Omphalos",
    blurb:
      "The sacred navel-stone of Delphi alone in the cella, a robed figure approaching through deep silence.",
  },
  {
    n: "04",
    key: "archive",
    name: "The Archive",
    blurb:
      "A vast Greek archive of scrolls and codices. A single scribe reads at the centre.",
  },
];

export default function PreviewPage() {
  return (
    <>
      <Nav />
      <main className="min-h-screen bg-[var(--bg)] text-[var(--fg)]">
        <header className="px-8 md:px-12 pt-16 pb-10 border-b border-[var(--line)]">
          <Link
            href="/"
            className="text-[12px] text-[var(--fg-mute)] hover:text-[var(--fg)] font-mono uppercase tracking-[0.2em]"
          >
            ← back to /
          </Link>
          <h1 className="font-serif text-[44px] md:text-[64px] leading-[1.05] tracking-[-0.015em] text-[var(--fg-strong)] mt-6">
            Hero candidates.
          </h1>
          <p className="mt-4 text-[var(--fg-dim)] text-[15.5px] max-w-[640px] leading-[1.6]">
            Each scene was generated in both dark and light polarity. Use
            the theme toggle in the nav to compare.
          </p>
        </header>

        {VARIANTS.map((v) => (
          <section
            key={v.key}
            className="border-t border-[var(--line)]"
          >
            <div className="relative w-full overflow-hidden bg-[var(--bg-deep)]">
              <div className="relative h-[58vh] min-h-[420px] max-h-[720px] w-full">
                <Image
                  src={`/img/heroes/${v.key}.png`}
                  alt={v.name}
                  fill
                  sizes="100vw"
                  className="dark-only object-cover object-center select-none"
                />
                <Image
                  src={`/img/heroes/${v.key}-light.png`}
                  alt={v.name}
                  fill
                  sizes="100vw"
                  className="light-only object-cover object-center select-none"
                />
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-[var(--bg)]" />
              </div>
            </div>
            <div className="px-8 md:px-12 py-12">
              <p className="text-[11px] font-mono uppercase tracking-[0.22em] text-[var(--fg-mute)]">
                {v.n} / 04
              </p>
              <h2 className="mt-3 font-serif text-[34px] md:text-[44px] leading-[1.05] tracking-[-0.01em] text-[var(--fg-strong)]">
                {v.name}.
              </h2>
              <p className="mt-3 text-[var(--fg-dim)] text-[16px] leading-[1.65] max-w-[680px]">
                {v.blurb}
              </p>
              <p className="mt-5 text-[12px] font-mono uppercase tracking-[0.18em] text-[var(--fg-mute)]">
                variant: {v.key}
              </p>
            </div>
          </section>
        ))}
      </main>
    </>
  );
}
