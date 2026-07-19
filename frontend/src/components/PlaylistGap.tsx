import type { UnmatchedTrack } from "../services/api";

/**
 * The round's tracks that didn't make an auto-generated playlist (MYS-201) —
 * source-only Bandcamp/YouTube picks and the odd catalog track a service
 * couldn't find. Plain and informational: a quiet muted label + list, never
 * alarming and never the screen's Rust signal. Renders nothing when the
 * playlist covers everything.
 */
export function PlaylistGap({ unmatched }: { unmatched: UnmatchedTrack[] }) {
  if (unmatched.length === 0) return null;
  return (
    <div className="mt-2">
      <p className="font-mono uppercase tracking-label text-[9px] text-muted">
        {unmatched.length === 1
          ? "1 track isn't on this playlist"
          : `${unmatched.length} tracks aren't on this playlist`}
      </p>
      <ul className="mt-2 space-y-1">
        {unmatched.map((t) => (
          <li key={t.submission_id} className="font-mono text-[11px] font-light text-muted">
            {t.title}
            {t.artist ? ` · ${t.artist}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
