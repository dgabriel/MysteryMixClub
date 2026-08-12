/**
 * Rendered stroke = strokeWidth x (size / viewBox). A 12-unit viewBox drawn at
 * 10px scaled the old 1 down to 0.83px — below the style guide's 1px floor,
 * and sub-pixel light strokes degrade badly on a near-black page.
 * strokeWidth 1.5 renders at 1.25px, matching Crown and MusicNote.
 */
export function MedalIcon({ className }: { className?: string }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <path d="M3.5 6.5 L2.5 11 L6 9.3 L9.5 11 L8.5 6.5" />
      <circle cx="6" cy="4.5" r="3.5" />
    </svg>
  );
}
