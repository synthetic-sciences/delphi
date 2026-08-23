export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <img
      alt=""
      aria-hidden="true"
      className={className}
      draggable="false"
      src="/icon.svg"
    />
  );
}
