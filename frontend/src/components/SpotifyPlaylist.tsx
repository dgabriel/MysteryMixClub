import { useEffect, useState } from "react";
import { MusicNoteIcon } from "./MusicNoteIcon";
import { getSpotifyPlaylistLink, type PlaylistJobStatus } from "../services/api";

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
 */

const LINK_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";
const NOTE_CLASS = "font-mono text-[13px] font-light text-muted";

// How often to re-check while a job is queued/running. Plain polling (ADR
// 0006) — not fast enough to feel like a live stream, fast enough that a
// member watching the mix page sees the link appear without a manual refresh.
const POLL_INTERVAL_MS = 7000;

const IN_PROGRESS_STATUSES: PlaylistJobStatus[] = ["queued", "running"];

type LinkState = {
  playlistUrl: string | null;
  status: PlaylistJobStatus | null;
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
          setState({ playlistUrl: r.playlist_url, status: r.status });
          if (r.status && IN_PROGRESS_STATUSES.includes(r.status)) {
            timer = setTimeout(fetchOnce, POLL_INTERVAL_MS);
          }
        })
        .catch(() => {
          if (active) setState({ playlistUrl: null, status: null });
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

  const { playlistUrl, status } = state;
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
    </div>
  );
}
