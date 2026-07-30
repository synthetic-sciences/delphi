import Image from "next/image";
import { ReactNode } from "react";

export type Variant = "pythia" | "sacred-way" | "omphalos" | "archive";

const ALT: Record<Variant, string> = {
  pythia:
    "The Pythia seated on a bronze tripod inside the inner sanctum of the Temple of Apollo at Delphi.",
  "sacred-way":
    "A robed scholar climbing the Sacred Way of Delphi, the Temple of Apollo silhouetted on Mount Parnassus.",
  omphalos:
    "The sacred omphalos stone of Delphi alone in the cella of the Temple of Apollo, a robed figure approaching.",
  archive:
    "A vast Greek archive of scrolls and codices, a scribe reading by lamplight.",
};

// The masters are 1408x768. Declaring that ratio lets "natural" mode lay the
// plate out at its own proportions instead of cropping it to whatever box it
// lands in.
const MASTER_W = 1408;
const MASTER_H = 768;

export function ThemedImage({
  variant,
  priority = false,
  fit = "cover",
}: {
  variant: Variant;
  priority?: boolean;
  /** "cover" fills its container and crops. "natural" keeps the plate's own
   *  aspect ratio, so nothing is cut off the top or bottom of the engraving. */
  fit?: "cover" | "natural";
}) {
  // Both variants are rendered into the DOM. CSS shows the matching theme.
  // The light variant is a duotone derived from the dark master, so the
  // two PNGs are pixel-perfect aligned — no content shift on toggle.
  const sizing =
    fit === "natural"
      ? { width: MASTER_W, height: MASTER_H, box: "h-auto w-full" }
      : { fill: true as const, box: "object-cover object-center" };
  const { box, ...dimensions } = sizing;

  return (
    <>
      <Image
        src={`/img/heroes/${variant}.png`}
        alt={ALT[variant]}
        {...dimensions}
        fetchPriority={priority ? "high" : undefined}
        priority={priority}
        sizes="100vw"
        className={`dark-only select-none ${box}`}
      />
      <Image
        src={`/img/heroes/${variant}-light.png`}
        alt={ALT[variant]}
        {...dimensions}
        fetchPriority={priority ? "high" : undefined}
        priority={priority}
        sizes="100vw"
        className={`light-only select-none ${box}`}
      />
    </>
  );
}

export function ClosingImage({
  variant = "archive",
  children,
}: {
  variant?: Variant;
  children?: ReactNode;
}) {
  return (
    <div className="relative min-h-[72vh] overflow-hidden border-t border-[var(--line)] bg-[#070605] text-[#f7f0dc]">
      <ThemedImage variant={variant} />
      {/* A flat 58% wash over the whole plate used to be the only overlay,
          which muddied the engraving and still left the headline sitting on
          the busiest part of it. Now the wash is light, and a bottom scrim
          carries the copy band to solid instead. */}
      <div className="absolute inset-0 bg-[rgba(4,4,3,0.3)]" />
      <div className="hero-scrim" />
      {children && (
        <div className="relative z-10 mx-auto flex min-h-[72vh] w-full max-w-[1240px] items-end px-5 py-14 sm:px-8 md:py-20">
          {children}
        </div>
      )}
    </div>
  );
}
