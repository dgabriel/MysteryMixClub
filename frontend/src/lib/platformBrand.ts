/**
 * Third-party streaming-service brand colors.
 *
 * These are NOT design tokens and deliberately do not live in
 * tailwind.config.js. They are the same category as Google's Sign-In button
 * (ADR 0007): values owned by another company's brand guidelines, which we
 * reproduce rather than restyle. Putting them in the theme would imply the
 * design system owns them and invite a future palette pass to "harmonize"
 * them, which we are not permitted to do.
 *
 * Because the values are third-party constants rather than tokens, they are
 * applied via inline `style`, not `className` — Tailwind's JIT cannot see a
 * runtime-computed class string, and an arbitrary-value class would be a raw
 * hex in JSX, which the style guide forbids.
 *
 * Only the services the app actually renders a badge for are listed. The style
 * guide also records Apple Music #FC3C44, Spotify #1DB954, Deezer #EF5466 and
 * Tidal #00FFFF; add one here only when a component needs it.
 *
 * `tint` / `edge` are the brand hue at ~6% and ~25% alpha, matching the design
 * system's PlatformBadge treatment.
 *
 * CONTRAST — this is a hard placement constraint, not a rounding concern.
 * The brand text is read against its own tint composited over the surface
 * below, so the surface changes the ratio. Measured:
 *
 *              floor   sunken   card    popover   tile
 *   youtube    5.04     4.91    4.74     4.40     4.22  <- AA FAIL at tile
 *   bandcamp   6.41     6.24    5.98     5.48     5.23
 *
 * A brand-tinted badge is therefore valid on `floor` / `sunken` / `card` /
 * `popover` ONLY. Do not place one on `tile` or above.
 */

/**
 * The services this module has brand values for. `SourceBadge` takes its
 * `source` prop as this type, so `SourceBadge` cannot be widened to accept a
 * service that `PLATFORM_BRAND` has no entry for — the `Record` below would
 * fail to typecheck first.
 *
 * That guarantee stops at the component boundary. `services/api.ts` hand-writes
 * `source: "youtube" | "bandcamp" | null` in six places with no link to this
 * type, so adding a third source there surfaces as an error at each
 * `<SourceBadge source={...} />` call site rather than here. Wiring api.ts to
 * this type would point the data layer at a presentation constant, so the
 * duplication is left in place deliberately; the sweep ticket can hoist a
 * shared `SongSource` type if it wants one.
 */
export type PlatformBrandKey = "youtube" | "bandcamp";

export const PLATFORM_BRAND: Record<
  PlatformBrandKey,
  { text: string; tint: string; edge: string }
> = {
  youtube: { text: "#FF0000", tint: "#FF000010", edge: "#FF000040" },
  bandcamp: { text: "#1DA0C3", tint: "#1DA0C310", edge: "#1DA0C340" },
};
