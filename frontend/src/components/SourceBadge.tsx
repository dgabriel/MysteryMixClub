import { Badge } from "./Badge";

/**
 * Marks a source-only track (MYS-201) — a Bandcamp/YouTube pick with no catalog
 * ISRC. A plain Default (Sage) badge: informational, never the Rust signal, so
 * it can sit freely alongside a screen's one Rust use.
 */
export function SourceBadge({ source }: { source: "youtube" | "bandcamp" }) {
  return <Badge>{source === "bandcamp" ? "bandcamp only" : "youtube only"}</Badge>;
}
