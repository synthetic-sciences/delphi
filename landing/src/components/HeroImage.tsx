import Image from "next/image";

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

const MASTER_W = 1408;
const MASTER_H = 768;

export function ThemedImage({
  variant,
  priority = false,
  fit = "cover",
}: {
  variant: Variant;
  priority?: boolean;
  fit?: "cover" | "natural";
}) {
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
