import { useEffect, useState } from "react";
import { MusicNoteIcon } from "./MusicNoteIcon";
import { getSpotifyPlaylistLink, type PlaylistJobStatus, type UnmatchedTrack } from "../services/api";

/**
 * Read-only Spotify playlist link for a mix (MYS-83, MYS-169).
 *
 * Generation is platform-admin only (a dedicated admin-screen action) — this
 * component never triggers it, only reads whatever link the admin already
 * produced. Self-contained: fetches its own link on mount and renders either
 * the link or a quiet "no spotify playlist yet" note. No busy/error states —
 * a failed fetch degrades to the same "not yet" note as "nothing generated".
 *
 * Generation now runs in a background worker, not inline in the request that
 * opens voting (MYS-258, ADR 0006), so the playlist usually doesn't exist yet
 * on first load. While the job is `queued`/`running`, this polls every
 * `POLL_INTERVAL_MS` and swaps in the link the moment it's ready — plain
 * polling, per the ADR (SSE is explicitly deferred, not needed at this
 * app's scale). A `failed` job still degrades to the same quiet "not yet"
 * note as no job at all, matching this component's existing no-error-state
 * philosophy above.
 *
 * Stays firmly in the Sage/Ink family — a sage underline-style link mirroring
 * the YouTube link. No Rust: on the voting screen that single signal is reserved
 * for the selected song.
 *
 * Also lists any submissions that didn't make the playlist (`unmatched`,
 * MYS-201/GH-232) — the backend recomputes this on every fetch regardless of
 * job status, so it's shown whenever present rather than gated on `complete`.
 * A `source_only` track links back out to its original source. When at least
 * one unmatched track resolved to a YouTube id, `overflow_youtube_url`
 * (GH-232) offers a single ad-hoc link that plays all of them at once.
 */

const LINK_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";
const NOTE_CLASS = "font-mono text-[13px] font-light text-muted";

// How often to re-check while a job is queued/running. Plain polling (ADR
// 0006) — not fast enough to feel like a live stream, fast enough that a
// member watching the mix page sees the link appear without a manual refresh.
const POLL_INTERVAL_MS = 7000;

const IN_PROGRESS_STATUSES: PlaylistJobStatus[] = ["queued", "running"];

// Human-readable reason text (MYS-201): `source_only` tracks were never in
// any streaming catalog to begin with, `no_catalog_match` tracks are catalog
// tracks Spotify's search just couldn't resolve.
function reasonLabel(track: UnmatchedTrack): string {
  return track.reason === "source_only" ? "not on spotify" : "not found on spotify";
}

type LinkState = {
  playlistUrl: string | null;
  status: PlaylistJobStatus | null;
  unmatched: UnmatchedTrack[];
  overflowYoutubeUrl: string | null;
};

export function SpotifyPlaylist({ mixId }: { mixId: string }) {
  const [state, setState] = useState<LinkState | undefined>(undefined);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const fetchOnce = () => {
      getSpotifyPlaylistLink(mixId)
        .then((r) => {
          if (!active) return;
          setState({
            playlistUrl: r.playlist_url,
            status: r.status,
            unmatched: r.unmatched,
            overflowYoutubeUrl: r.overflow_youtube_url,
          });
          if (r.status && IN_PROGRESS_STATUSES.includes(r.status)) {
            timer = setTimeout(fetchOnce, POLL_INTERVAL_MS);
          }
        })
        .catch(() => {
          if (active)
            setState({ playlistUrl: null, status: null, unmatched: [], overflowYoutubeUrl: null });
        });
    };

    fetchOnce();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [mixId]);

  // undefined = still loading; render nothing rather than a flash of the note.
  if (state === undefined) return null;

  const { playlistUrl, status, unmatched, overflowYoutubeUrl } = state;
  const inProgress = !playlistUrl && !!status && IN_PROGRESS_STATUSES.includes(status);

  return (
    <div className="mb-8">
      {playlistUrl ? (
        <a href={playlistUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
          <MusicNoteIcon />
          open playlist in Spotify
        </a>
      ) : inProgress ? (
        <p className={NOTE_CLASS}>generating spotify playlist&hellip;</p>
      ) : (
        <p className={NOTE_CLASS}>no spotify playlist yet</p>
      )}
      {unmatched.length > 0 ? (
        <div className="mt-2">
          <p className={NOTE_CLASS}>
            {unmatched.length} {unmatched.length === 1 ? "song didn't" : "songs didn't"} make the
            spotify playlist:
          </p>
          {overflowYoutubeUrl ? (
            <a
              href={overflowYoutubeUrl}
              target="_blank"
              rel="noopener noreferrer"
              className={`${LINK_CLASS} mt-1`}
            >
              <MusicNoteIcon />
              hear the rest on youtube
            </a>
          ) : null}
          <ul className="mt-1 space-y-1">
            {unmatched.map((track) => (
              <li key={track.submission_id} className={NOTE_CLASS}>
                {track.title} by {track.artist} ({reasonLabel(track)}
                {track.source_url ? (
                  <>
                    ,{" "}
                    <a
                      href={track.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={LINK_CLASS}
                    >
                      listen on {track.source}
                    </a>
                  </>
                ) : null}
                )
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
