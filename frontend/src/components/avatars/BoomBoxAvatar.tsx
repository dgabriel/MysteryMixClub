export function BoomBoxAvatar({ size = 48 }: { size?: number }) {
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
      {/* Main body */}
      <rect x="2" y="9" width="28" height="18" rx="2" />
      {/* Carry handle */}
      <path d="M10 9 Q16 5 22 9" />
      {/* Left speaker */}
      <circle cx="8" cy="18" r="4.5" />
      <circle cx="8" cy="18" r="2" />
      {/* Right speaker */}
      <circle cx="24" cy="18" r="4.5" />
      <circle cx="24" cy="18" r="2" />
      {/* Cassette slot (center) */}
      <rect x="14" y="12" width="4" height="9" rx="0.5" />
      {/* Mini reels in slot */}
      <circle cx="15.5" cy="16.5" r="1.5" />
      <circle cx="18.5" cy="16.5" r="1.5" />
      {/* Antenna */}
      <line x1="27" y1="9" x2="30.5" y2="3" />
      {/* Tuning knob */}
      <circle cx="16" cy="11" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
