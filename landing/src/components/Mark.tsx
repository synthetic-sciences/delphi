/* The Delphi mark: one query fanning out to three sources. Inherits currentColor. */
export function Mark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round">
        <path d="M18 32 C 30 32, 34 14, 48 14" />
        <path d="M18 32 H 48" />
        <path d="M18 32 C 30 32, 34 50, 48 50" />
      </g>
      <g fill="currentColor">
        <circle cx="15" cy="32" r="5.5" />
        <circle cx="50" cy="14" r="4" />
        <circle cx="50" cy="32" r="4" />
        <circle cx="50" cy="50" r="4" />
      </g>
    </svg>
  );
}
