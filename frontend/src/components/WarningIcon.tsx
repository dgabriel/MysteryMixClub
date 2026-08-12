/**
 * Rendered stroke = strokeWidth x (size / viewBox). A 24-unit viewBox drawn at
 * 12px halves it, so the old 1.5 landed at 0.75px — below the style guide's
 * 1px floor, and sub-pixel light strokes degrade badly on a near-black page.
 * strokeWidth 2 renders at exactly 1px. The inner filled dot is unaffected.
 */
export function WarningIcon({ className }: { className?: string }) {
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
      <path d="M12 3.5 22 20.5H2z" />
      <line x1="12" y1="9.5" x2="12" y2="14" />
      <circle cx="12" cy="17" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}
