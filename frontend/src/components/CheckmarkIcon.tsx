export function CheckmarkIcon({ className }: { className?: string }) {
  return (
    <svg
      width="9"
      height="9"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <polyline points="1.5 6.5 4.5 9.5 10.5 2.5" />
    </svg>
  );
}
