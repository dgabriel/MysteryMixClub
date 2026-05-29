type ConcentricRingsProps = {
  /** pixel diameter of the outermost ring */
  size?: number;
  /** slowly rotate the rings — used for loading states */
  spinning?: boolean;
  /** show the single off-center Rust dot ("the fish"). Counts as the screen's one Rust use. */
  accent?: boolean;
  className?: string;
};

/**
 * The MysteryMixClub signature motif — concentric rings referencing Duchamp's
 * Rotorelief. Sage family layered inward. An optional single Rust dot may sit
 * off-center; when present it is the screen's one permitted Rust accent.
 */
export function ConcentricRings({
  size = 96,
  spinning = false,
  accent = false,
  className = "",
}: ConcentricRingsProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      role="presentation"
      aria-hidden="true"
      className={[spinning ? "animate-rotate-rings" : "", className]
        .filter(Boolean)
        .join(" ")}
    >
      <circle cx="50" cy="50" r="46" fill="none" className="stroke-sage-pale" strokeWidth="2" />
      <circle cx="50" cy="50" r="34" fill="none" className="stroke-sage-light" strokeWidth="2" />
      <circle cx="50" cy="50" r="22" fill="none" className="stroke-sage" strokeWidth="2" />
      <circle cx="50" cy="50" r="10" fill="none" className="stroke-sage" strokeWidth="2" />
      {accent ? <circle cx="50" cy="16" r="3.5" className="fill-rust" /> : null}
    </svg>
  );
}
