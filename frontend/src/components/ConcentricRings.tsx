type ConcentricRingsProps = {
  /** pixel diameter of the disc */
  size?: number;
  /** slowly rotate the disc — used for loading states */
  spinning?: boolean;
  /** show the amber centre label. This is the brand mark, and amber-as-identity
   *  is its own category alongside action and achievement — see the identity
   *  exception in the style guide. Without it the label renders neutral. */
  accent?: boolean;
  className?: string;
};

/** Literal color values for the disc's CSS gradients. A gradient stop and a
 *  pixel-sized inner dot cannot read a Tailwind class, so this is the one place
 *  in the component where a raw value is correct. Every entry maps 1:1 onto a
 *  named token in `tailwind.config.js` — named here so the R18 sweep can find
 *  them if a token value ever moves. */
const DISC = {
  /** `card` — the vinyl itself, one step above `floor` */
  surface: "#0D0D0F",
  /** `hairline-soft` — the groove highlight. A gradient stop, not a border, so
   *  the fixed-alpha hairline ladder is being reused for its value rather than
   *  its role. The style tile uses 0.02 here; that vanishes entirely at 28px. */
  groove: "rgba(255, 255, 255, 0.05)",
  /** `floor` — the spindle hole punched through the label */
  spindle: "#030304",
  /** `panel` → `tile` — neutral centre label */
  labelNeutralHigh: "#28292A",
  labelNeutralLow: "#1A1B1C",
  /** `accent-hover` → `accent` — the amber centre label of the brand mark */
  labelAccentHigh: "#FDA258",
  labelAccentLow: "#F3821D",
} as const;

/** The style tile drops its secondary label under 60px; the same threshold
 *  governs this component's secondary detail. */
const DETAIL_MIN = 60;

/**
 * The MysteryMixClub signature motif — the record. A `card`-dark platter with
 * a groove texture, a centre label, a spindle hole, and `shadow-art`, whose 1px
 * white ring is what makes it read as an object on a near-black page.
 *
 * It keeps the `ConcentricRings` name because a record *is* concentric rings:
 * this is a translation of the motif, not a replacement of it.
 *
 * Grooves are laid out in physical pixels rather than viewBox units so the
 * texture stays constant across the 28px (nav mark) to 88px (page hero) range
 * this ships at, instead of blurring to sub-pixel mush when scaled down.
 */
export function ConcentricRings({
  size = 96,
  spinning = false,
  accent = false,
  className = "",
}: ConcentricRingsProps) {
  const detailed = size >= DETAIL_MIN;
  const label = Math.round(size * 0.54);
  const spindle = Math.round(size * 0.06);
  // A 28px mark leaves only a ~6px annulus outside the label, so the compact
  // size tightens the groove period to keep visible texture in it.
  const period = detailed ? 4 : 3;

  return (
    <div
      role="presentation"
      aria-hidden="true"
      className={[
        "flex shrink-0 items-center justify-center rounded-full shadow-art",
        spinning ? "animate-rotate-rings" : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      style={{
        width: size,
        height: size,
        background: `repeating-radial-gradient(circle at 50% 50%, transparent 0, transparent ${
          period - 1
        }px, ${DISC.groove} ${period - 1}px, ${DISC.groove} ${period}px), ${DISC.surface}`,
      }}
    >
      <div
        className="flex shrink-0 items-center justify-center rounded-full"
        style={{
          width: label,
          height: label,
          background: accent
            ? `radial-gradient(circle at 38% 35%, ${DISC.labelAccentHigh}, ${DISC.labelAccentLow})`
            : `radial-gradient(circle at 38% 35%, ${DISC.labelNeutralHigh}, ${DISC.labelNeutralLow})`,
        }}
      >
        {detailed ? (
          <span
            className="block shrink-0 rounded-full"
            style={{ width: spindle, height: spindle, background: DISC.spindle }}
          />
        ) : null}
      </div>
    </div>
  );
}
