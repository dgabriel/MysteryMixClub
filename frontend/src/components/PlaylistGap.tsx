import type { UnmatchedTrack } from "../services/api";

const TITLE_LINK_CLASS =
  "font-mono text-[11px] font-light text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";

/**
 * The round's tracks that didn't make an auto-generated playlist (MYS-201) —
 * source-only Bandcamp/YouTube picks and the odd catalog track a service
 * couldn't find. A top callout (renders before the playlist link) so a listener
 * sees the gap first, but still calm and informational: an Ink label over a
 * muted list, never alarming and never the screen's Rust signal. A source-only
 * track's title links out to its Bandcamp/YouTube page; a no-catalog-match track
 * has nowhere to send them, so its title stays plain. Renders nothing when the
 * playlist covers everything.
 */
export function PlaylistGap({ unmatched }: { unmatched: UnmatchedTrack[] }) {
  if (unmatched.length === 0) return null;
  return (
    <div className="mb-3 border-l-2 border-sage-light pl-3">
      <p className="font-mono uppercase tracking-label text-[11px] text-ink">
        {unmatched.length === 1
          ? "1 track isn't on this playlist"
          : `${unmatched.length} tracks aren't on this playlist`}
      </p>
      <ul className="mt-2 space-y-1">
        {unmatched.map((t) => (
          <li key={t.submission_id} className="font-mono text-[11px] font-light text-muted">
            {t.source_url ? (
              <a
                href={t.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className={TITLE_LINK_CLASS}
              >
                {t.title}
              </a>
            ) : (
              t.title
            )}
            {t.artist ? ` · ${t.artist}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
