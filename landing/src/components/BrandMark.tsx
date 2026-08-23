export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 100 100"
    >
      <ellipse
        cx="50"
        cy="50"
        rx="39"
        ry="15"
        stroke="currentColor"
        strokeWidth="6"
      />
      <ellipse
        cx="50"
        cy="50"
        rx="39"
        ry="15"
        stroke="currentColor"
        strokeWidth="6"
        transform="rotate(60 50 50)"
      />
      <ellipse
        cx="50"
        cy="50"
        rx="39"
        ry="15"
        stroke="currentColor"
        strokeWidth="6"
        transform="rotate(120 50 50)"
      />
      <path
        d="M42 37 67 50 42 64Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="5"
      />
    </svg>
  );
}
