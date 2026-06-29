export function WalkmanAvatar({ size = 48 }: { size?: number }) {
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
      {/* Body */}
      <rect x="7" y="2" width="18" height="28" rx="3" />
      {/* Cassette window */}
      <rect x="10" y="5" width="12" height="10" rx="1" />
      {/* Left reel */}
      <circle cx="14" cy="10" r="3" />
      <circle cx="14" cy="10" r="1.25" />
      {/* Right reel */}
      <circle cx="18" cy="10" r="3" />
      <circle cx="18" cy="10" r="1.25" />
      {/* Button strip */}
      <rect x="10" y="18" width="12" height="6" rx="1" />
      {/* Play triangle */}
      <path d="M13.5 19.5 L13.5 22.5 L17 21 Z" fill="currentColor" stroke="none" />
      {/* Stop square */}
      <rect x="18" y="20" width="2.5" height="2.5" rx="0.25" fill="currentColor" stroke="none" />
      {/* Headphone jack at bottom */}
      <circle cx="16" cy="28.5" r="1" />
      {/* Belt clip on right side */}
      <path d="M25 6 L25 26" />
      <path d="M25 6 Q27 6 27 8 L27 24 Q27 26 25 26" />
    </svg>
  );
}
