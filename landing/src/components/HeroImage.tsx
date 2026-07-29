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

export function ThemedImage({
  variant,
  priority = false,
}: {
  variant: Variant;
  priority?: boolean;
}) {
  // Both variants are rendered into the DOM. CSS shows the matching theme.
  // The light variant is a duotone derived from the dark master, so the
  // two PNGs are pixel-perfect aligned — no content shift on toggle.
  return (
    <>
      <Image
        src={`/img/heroes/${variant}.png`}
        alt={ALT[variant]}
        fill
        fetchPriority={priority ? "high" : undefined}
        sizes="100vw"
        className="dark-only object-cover object-center select-none"
      />
      <Image
        src={`/img/heroes/${variant}-light.png`}
        alt={ALT[variant]}
        fill
        fetchPriority={priority ? "high" : undefined}
        sizes="100vw"
        className="light-only object-cover object-center select-none"
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
      <div className="absolute inset-0 bg-[rgba(4,4,3,0.58)]" />
      <div className="absolute inset-0 bg-gradient-to-b from-[var(--bg)] via-transparent to-[#070605]" />
      {children && (
        <div className="relative z-10 mx-auto flex min-h-[72vh] w-full max-w-[1240px] items-end px-5 py-14 sm:px-8 md:py-20">
          {children}
        </div>
      )}
    </div>
  );
}
