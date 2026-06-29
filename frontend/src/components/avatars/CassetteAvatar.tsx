export function CassetteAvatar({ size = 48 }: { size?: number }) {
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
      {/* Outer shell */}
      <rect x="2" y="5" width="28" height="22" rx="2.5" />
      {/* Tape window */}
      <rect x="6" y="9" width="20" height="11" rx="1" />
      {/* Left reel */}
      <circle cx="12" cy="14.5" r="3.5" />
      <circle cx="12" cy="14.5" r="1.5" />
      {/* Right reel */}
      <circle cx="20" cy="14.5" r="3.5" />
      <circle cx="20" cy="14.5" r="1.5" />
      {/* Tape guide line across bottom of window */}
      <path d="M8 20 L24 20" />
      {/* Bottom alignment tabs */}
      <rect x="5" y="23.5" width="3.5" height="2.5" rx="0.5" />
      <rect x="23.5" y="23.5" width="3.5" height="2.5" rx="0.5" />
    </svg>
  );
}
