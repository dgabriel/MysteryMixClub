export function FlyingVAvatar({ size = 48 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* Headstock */}
      <rect x="12" y="1" width="8" height="3.5" rx="1" />
      {/* Tuning pegs — 3 left, 3 right */}
      <line x1="12" y1="2" x2="9.5" y2="2" />
      <circle cx="9" cy="2" r="0.75" fill="currentColor" stroke="none" />
      <line x1="12" y1="3.5" x2="9.5" y2="3.5" />
      <circle cx="9" cy="3.5" r="0.75" fill="currentColor" stroke="none" />
      <line x1="20" y1="2" x2="22.5" y2="2" />
      <circle cx="23" cy="2" r="0.75" fill="currentColor" stroke="none" />
      <line x1="20" y1="3.5" x2="22.5" y2="3.5" />
      <circle cx="23" cy="3.5" r="0.75" fill="currentColor" stroke="none" />
      {/* Neck */}
      <rect x="14" y="4.5" width="4" height="13" rx="0.75" />
      {/* Frets */}
      <line x1="14" y1="7.5" x2="18" y2="7.5" />
      <line x1="14" y1="11" x2="18" y2="11" />
      <line x1="14" y1="14" x2="18" y2="14" />
      {/* V-shaped body */}
      <path d="M14 16 L2.5 29.5 L6 31 L16 23 L26 31 L29.5 29.5 L18 16 Z" />
      {/* Pickup */}
      <rect x="14.5" y="23" width="3" height="2" rx="0.5" />
    </svg>
  );
}
