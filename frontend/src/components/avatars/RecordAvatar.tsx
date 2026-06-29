export function RecordAvatar({ size = 48 }: { size?: number }) {
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
      {/* Outer groove */}
      <circle cx="16" cy="16" r="14" />
      {/* Groove rings — echoes the Rotorelief motif */}
      <circle cx="16" cy="16" r="10.5" />
      <circle cx="16" cy="16" r="7" />
      {/* Label */}
      <circle cx="16" cy="16" r="4" />
      {/* Center spindle hole */}
      <circle cx="16" cy="16" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  );
}
