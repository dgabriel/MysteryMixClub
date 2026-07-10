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
