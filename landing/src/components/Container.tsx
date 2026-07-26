import { ReactNode } from "react";
import clsx from "clsx";

export function Container({
  children,
  className,
  width = "default",
}: {
  children: ReactNode;
  className?: string;
  width?: "default" | "narrow" | "wide";
}) {
  const max =
    width === "narrow"
      ? "max-w-[680px]"
      : width === "wide"
        ? "max-w-[1100px]"
        : "max-w-[860px]";
  return (
    <div className={clsx("mx-auto w-full px-6 md:px-8", max, className)}>
      {children}
    </div>
  );
}
