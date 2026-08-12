import { PLATFORM_BRAND, type PlatformBrandKey } from "../lib/platformBrand";

/**
 * Marks a source-only track (MYS-201) — a Bandcamp/YouTube pick with no catalog
 * ISRC. Rendered in the platform's own brand tint rather than a system color:
 * the label names a third party, so it reads as that third party. The brand
 * hexes are not design tokens and live in `lib/platformBrand.ts` with the
 * ADR-0007 rationale.
 *
 * It renders its own span rather than delegating to `Badge`, because `Badge`
 * has no brand-tint variant and widening its `Variant` union would be a
 * props-interface change.
 *
 * PLACEMENT CONSTRAINT: brand text is read against its own tint composited
 * over the surface below, so this badge is only AA-safe on `floor`, `sunken`,
 * `card` or `popover`. YouTube red falls to 4.22:1 on `tile`. See the contrast
 * table in `lib/platformBrand.ts`.
 *
 * `text-mini`, not the `text-micro` the design system's own platform badge
 * uses: "youtube only" is information-bearing and `text-micro` is chrome only.
 */
export function SourceBadge({ source }: { source: PlatformBrandKey }) {
  const brand = PLATFORM_BRAND[source];
  return (
    <span
      className="inline-block rounded-hair border px-1.5 py-0.5 font-mono text-mini uppercase tracking-mono-caps"
      style={{ color: brand.text, backgroundColor: brand.tint, borderColor: brand.edge }}
    >
      {source === "bandcamp" ? "bandcamp only" : "youtube only"}
    </span>
  );
}
