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

function ThemedImage({
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

export function HeroImage({
  variant = "sacred-way",
}: {
  variant?: Variant;
}) {
  return (
    <ImageBand fadeBottom>
      <ThemedImage variant={variant} priority />
    </ImageBand>
  );
}

export function ClosingImage({
  variant = "archive",
}: {
  variant?: Variant;
}) {
  return (
    <ImageBand fadeTop border>
      <ThemedImage variant={variant} />
    </ImageBand>
  );
}

function ImageBand({
  children,
  fadeBottom = false,
  fadeTop = false,
  border = false,
}: {
  children: ReactNode;
  fadeBottom?: boolean;
  fadeTop?: boolean;
  border?: boolean;
}) {
  return (
    <div
      className={`relative w-full overflow-hidden bg-[var(--bg-deep)] ${border ? "border-t border-[var(--line)]" : ""}`}
    >
      <div className="relative h-[58vh] min-h-[420px] max-h-[720px] w-full">
        {children}
        {fadeBottom && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-b from-transparent to-[var(--bg)]" />
        )}
        {fadeTop && (
          <div className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-t from-transparent to-[var(--bg)]" />
        )}
      </div>
    </div>
  );
}
