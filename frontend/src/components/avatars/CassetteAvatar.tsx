type ReelProps = { cx: number; cy: number };

function Reel({ cx, cy }: ReelProps) {
  const holeR = 4;
  const holes = Array.from({ length: 6 }, (_, i) => {
    const a = (i * Math.PI * 2) / 6;
    return [cx + holeR * Math.cos(a), cy + holeR * Math.sin(a)] as const;
  });
  return (
    <g>
      <circle cx={cx} cy={cy} r={6} />
      {holes.map(([hx, hy], i) => (
        <circle key={i} cx={hx} cy={hy} r={0.85} fill="currentColor" stroke="none" />
      ))}
      <circle cx={cx} cy={cy} r={2} />
      <circle cx={cx} cy={cy} r={1} fill="currentColor" stroke="none" />
    </g>
  );
}

/** The one music-hardware avatar illustration. Strokes `currentColor`, so the
 *  color decision lives in `UserAvatar`.
 *
 *  `strokeWidth="1.5"` is in viewBox units and the 44×28 viewBox is fitted into
 *  a square box, so the rendered weight is `1.5 × size / 44`. At the sizes that
 *  actually ship — `UserAvatar` passes `size * 0.72`, so 35px from its own
 *  default 48 and 40px from ProfileScreen's 56 — that is 1.19px and 1.36px.
 *  Both clear the 1px floor and sit inside the style guide's 1–1.5px band, so
 *  the value is correct as-is. Below a 30px `size` it would drop under 1px. */
export function CassetteAvatar({ size = 48 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 44 28"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {/* Shell */}
      <rect x="0.75" y="0.75" width="42.5" height="26.5" rx="2.5" />
      {/* Label area */}
      <rect x="2.5" y="2.5" width="39" height="10" rx="1" />
      {/* Label lines */}
      <line x1="6" y1="5.5" x2="10" y2="5.5" />
      <line x1="6" y1="8" x2="14" y2="8" />
      {/* Reels */}
      <Reel cx={12.5} cy={19} />
      <Reel cx={31.5} cy={19} />
      {/* Tape-head slot */}
      <rect x="18.5" y="14.5" width="7" height="7" rx="0.75" />
      {/* Tape guides */}
      <circle cx={17.5} cy={21} r={0.75} fill="currentColor" stroke="none" />
      <circle cx={26.5} cy={21} r={0.75} fill="currentColor" stroke="none" />
      {/* Bottom alignment tabs */}
      <rect x="3" y="24.5" width="3.5" height="2.5" rx="0.5" />
      <rect x="9" y="24.5" width="3.5" height="2.5" rx="0.5" />
      <rect x="28.5" y="24.5" width="3.5" height="2.5" rx="0.5" />
      <rect x="37.5" y="24.5" width="3.5" height="2.5" rx="0.5" />
    </svg>
  );
}
