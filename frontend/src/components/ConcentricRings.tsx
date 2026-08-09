type ConcentricRingsProps = {
  /** pixel diameter of the disc */
  size?: number;
  /** slowly rotate the disc — used for loading states */
  spinning?: boolean;
  /** show the amber centre label — the disc as the brand mark. Without it the
   *  label renders neutral, which is what a spinner or a background motif wants.
   *  Placement is a design call, not a licence to obtain (ADR 0012). */
  accent?: boolean;
  /** set the `mmc` wordmark in the centre label, as the design system's hero
   *  disc does. Implies `accent`, and inverts the label: the wordmark is amber
   *  on a warm near-black rather than the label itself being an amber fill.
   *
   *  Only meaningful on a large disc. The DS sizes the wordmark at
   *  `size * 0.072`, so a 28px nav mark would set it at 2px — hence this is
   *  opt-in per call site rather than derived from `size`.
   *
   *  It is also what makes `spinning` legible: the grooves are concentric and
   *  therefore rotationally symmetric, so a disc with no wordmark rotates
   *  invisibly. */
  wordmark?: boolean;
  className?: string;
};

/** Literal color values for the disc's CSS gradients. A gradient stop and a
 *  pixel-sized inner dot cannot read a Tailwind class, so this is the one place
 *  in the component where a raw value is correct. Every entry maps 1:1 onto a
 *  named token in `tailwind.config.js` — named here so the R18 sweep can find
 *  them if a token value ever moves. */
const DISC = {
  /** `card` — the vinyl itself, one step above `floor`. The *neutral* disc: a
   *  spinner or a background motif, where the record is not being the brand. */
  surface: "#0D0D0F",
  /** `hairline` — the neutral disc's groove highlight. A gradient stop, not a
   *  border, so the fixed-alpha hairline ladder is reused for its value rather
   *  than its role. The style tile uses 0.02, which vanishes entirely at 28px;
   *  this sat at `hairline-soft` 0.05 until the grooves proved too faint to
   *  separate the disc from `floor`. */
  groove: "rgba(255, 255, 255, 0.09)",
  /** `accent-surface` — the *branded* disc's body. Together with `grooveBrand`
   *  this is the palette of the design system's "accent rationale" callout
   *  (DS `App.tsx:521`: `oklch(0.20 0.01 55)` on a `rgba(201,139,48,·)` edge),
   *  which is the warm amber-tinted register the record reads in when it is
   *  standing for the brand rather than spinning as chrome. */
  surfaceBrand: "#1A1512",
  /** `accent-hairline` — the branded disc's grooves. The DS callout sets its
   *  border at alpha 0.2; we ship the sanctioned `accent-hairline` step, 0.25,
   *  so this stays 1:1 with a named token rather than becoming a fourth ad hoc
   *  amber alpha. The difference is imperceptible at groove width. */
  grooveBrand: "rgba(201, 139, 48, 0.25)",
  /** `floor` — the spindle hole punched through the label */
  spindle: "#030304",
  /** `panel` → `tile` — neutral centre label */
  labelNeutralHigh: "#28292A",
  labelNeutralLow: "#1A1B1C",
  /** `accent-hover` → `accent` — the amber centre label of the brand mark, used
   *  at compact sizes where the wordmark cannot be set legibly */
  labelAccentHigh: "#FDA258",
  labelAccentLow: "#F3821D",
  /** The design system's own label for the branded disc (DS `App.tsx:107`): a
   *  warm near-black the amber wordmark sits *on*, rather than an amber fill. */
  labelBrandHigh: "#251A0E",
  labelBrandLow: "#150F0A",
  /** `accent` — the `mmc` wordmark set on `labelBrand*` */
  wordmarkInk: "#F3821D",
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
  wordmark = false,
  className = "",
}: ConcentricRingsProps) {
  const detailed = size >= DETAIL_MIN;
  const label = Math.round(size * 0.54);
  const spindle = Math.round(size * 0.06);
  // The warm palette belongs to the disc-as-brand-mark. A neutral disc is a
  // spinner or a background motif and stays on the cool surface ladder — an
  // amber-tinted loading state would read as a state change rather than chrome.
  const branded = accent || wordmark;
  const discSurface = branded ? DISC.surfaceBrand : DISC.surface;
  const grooveInk = branded ? DISC.grooveBrand : DISC.groove;
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
        }px, ${grooveInk} ${period - 1}px, ${grooveInk} ${period}px), ${discSurface}`,
      }}
    >
      <div
        className="flex shrink-0 items-center justify-center rounded-full"
        style={{
          width: label,
          height: label,
          background: wordmark
            ? `radial-gradient(circle at 38% 35%, ${DISC.labelBrandHigh}, ${DISC.labelBrandLow})`
            : accent
              ? `radial-gradient(circle at 38% 35%, ${DISC.labelAccentHigh}, ${DISC.labelAccentLow})`
              : `radial-gradient(circle at 38% 35%, ${DISC.labelNeutralHigh}, ${DISC.labelNeutralLow})`,
        }}
      >
        {wordmark ? (
          /* The wordmark replaces the spindle dot rather than joining it — the
             DS's label has no visible spindle, because its own spindle gradient
             sits under this opaque label. Sized at the DS's `size * 0.072`. */
          <span
            className="block select-none font-mono uppercase tracking-mono"
            style={{
              fontSize: Math.round(size * 0.072 * 10) / 10,
              lineHeight: 1,
              color: DISC.wordmarkInk,
            }}
          >
            mmc
          </span>
        ) : detailed ? (
          <span
            className="block shrink-0 rounded-full"
            style={{ width: spindle, height: spindle, background: DISC.spindle }}
          />
        ) : null}
      </div>
    </div>
  );
}
