export function MusicNoteIcon({ className }: { className?: string }) {
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
      <ellipse cx="3.5" cy="9.5" rx="2.5" ry="1.5" />
      <line x1="6" y1="8.5" x2="6" y2="1" />
      <path d="M6 1 Q10 2 10 5" />
    </svg>
  );
}
