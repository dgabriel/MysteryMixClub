import { useEffect, useState } from "react";
import { getSpotifyPlaylistLink, type UnmatchedTrack } from "../../services/api";
import { PlaylistLink } from "./PlaylistAction";
import { MusicNoteIcon } from "../MusicNoteIcon";

export type MaybeMissingTrack = {
  submission_id: string;
  title: string;
  artist: string;
  /** Where to hear it, when there is somewhere. Null for a catalog track a
   *  service simply failed to match — we know it is missing, not where it is. */
  source_url: string | null;
};

/**
 * One list of the songs that **may** not be on every generated playlist.
 *
 * Deliberately agnostic and deliberately non-exhaustive, which is the whole
 * design:
 *
 * - **Agnostic.** It does not say which service is missing which song. Per-row
 *   status already reports each service's completeness as a count; repeating
 *   the detail per service is what made the old layout a maze of near-identical
 *   links. A listener wants one answer to "what might I not hear", not a matrix.
 * - **Non-exhaustive, and it says so.** "May not be" is literal. The two things
 *   we can see are tracks with no catalog identity at all (Bandcamp/YouTube-only
 *   picks, MYS-201) and the tracks a service reported it could not match. A
 *   service can fail to match a song without telling us, and Apple only reports
 *   its gaps in the moment it builds a playlist. Promising a complete list would
 *   be a promise the data cannot keep.
 *
 * Sources are merged and de-duplicated by submission id: a Bandcamp-only track
 * is usually *also* in Spotify's unmatched list, and listing it twice would
 * suggest two different problems.
 */
export function SongsMaybeMissing({
  mixId,
  sourceOnly,
}: {
  mixId: string;
  /** Picks with no catalog identity — known from the mix itself, no fetch. */
  sourceOnly: MaybeMissingTrack[];
}) {
  const [reported, setReported] = useState<UnmatchedTrack[]>([]);
  const [overflowUrl, setOverflowUrl] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    // One fetch, no polling: this list matters once a playlist exists, and the
    // service rows already poll while one is being built.
    getSpotifyPlaylistLink(mixId)
      .then((r) => {
        if (!active) return;
        setReported(r.unmatched);
        setOverflowUrl(r.overflow_youtube_url);
      })
      .catch(() => {
        // A failure here means we simply know less. The section is already
        // hedged, so degrading to "what the mix itself tells us" is honest.
        if (active) {
          setReported([]);
          setOverflowUrl(null);
        }
      });
    return () => {
      active = false;
    };
  }, [mixId]);

  const bySubmission = new Map<string, MaybeMissingTrack>();
  for (const t of sourceOnly) bySubmission.set(t.submission_id, t);
  for (const t of reported) {
    if (!bySubmission.has(t.submission_id)) {
      bySubmission.set(t.submission_id, {
        submission_id: t.submission_id,
        title: t.title,
        artist: t.artist,
        source_url: t.source_url,
      });
    }
  }
  const tracks = [...bySubmission.values()];
  if (tracks.length === 0) return null;

  return (
    // `mb-10` matters as much as the heading: this butted straight into the
    // next section's heading, so the two read as one run of small grey type.
    <section className="mt-8 mb-10">
      {/* An h2 at `text-meta`/`tracking-mono-wide` — the same weight as every
          other section heading on this screen. It was an h3 at `text-mini`,
          which made the section quieter than the list it introduces and let it
          read as a footnote to the Apple row above rather than its own thing. */}
      <h2 className="font-mono uppercase tracking-mono-wide text-meta text-ink-muted">
        songs that may not be on all playlists
      </h2>
      <ul className="mt-3 space-y-1">
        {tracks.map((t) => (
          <li key={t.submission_id} className="font-mono text-meta text-ink-muted">
            {t.source_url ? (
              <a
                href={t.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-ink underline underline-offset-[3px] transition-colors duration-150 hover:text-ink-link"
              >
                {t.title}
              </a>
            ) : (
              <span className="text-ink">{t.title}</span>
            )}
            {t.artist ? ` · ${t.artist}` : ""}
          </li>
        ))}
      </ul>
      {overflowUrl ? (
        <div className="mt-4">
          <PlaylistLink href={overflowUrl} label="hear the songs missing from spotify, on youtube">
            <MusicNoteIcon />
            hear these on youtube
          </PlaylistLink>
        </div>
      ) : null}
    </section>
  );
}
