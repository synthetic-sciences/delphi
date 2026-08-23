export function BrandMark({ className = "" }: { className?: string }) {
  return <span aria-hidden="true" className={`brand-mark ${className}`} />;
}
