export type Variant = "sacred-way" | "archive";

const ALT: Record<Variant, string> = {
  "sacred-way":
    "A robed scholar climbing the Sacred Way of Delphi, the Temple of Apollo silhouetted on Mount Parnassus.",
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
  return (
    <span
      aria-label={ALT[variant]}
      className="themed-image"
      data-priority={priority ? "true" : undefined}
      data-variant={variant}
      role="img"
    />
  );
}
