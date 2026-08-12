/**
 * Rendered stroke = strokeWidth x (size / viewBox). A 24-unit viewBox drawn at
 * 12px halves it, so the old 1.5 landed at 0.75px — below the style guide's
 * 1px floor. A sub-pixel light stroke antialiases away far more perceived
 * contrast on a near-black page than a dark one ever did on cream.
 * strokeWidth 2 renders at exactly 1px.
 */
export function ClockIcon({ className }: { className?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15 14" />
    </svg>
  );
}
