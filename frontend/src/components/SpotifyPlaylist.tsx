import { useEffect, useState } from "react";
import { MusicNoteIcon } from "./MusicNoteIcon";
import { PlaylistRow } from "./playlists/PlaylistRow";
import { PlaylistLink } from "./playlists/PlaylistAction";
import {
  getSpotifyPlaylistLink,
  type PlaylistJobStatus,
  type UnmatchedTrack,
} from "../services/api";

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
 * Also lists any submissions that didn't make the playlist (`unmatched`,
 * MYS-201/GH-232) — the backend recomputes this on every fetch regardless of
 * job status, so it's shown whenever present rather than gated on `complete`.
 * A `source_only` track links back out to its original source. When at least
 * one unmatched track resolved to a YouTube id, `overflow_youtube_url`
 * (GH-232) offers a single ad-hoc link that plays all of them at once.
 *
 * **No Spotify green anywhere.** Third-party brand values live in
 * `lib/platformBrand.ts`, not in the theme, and this component has never used
 * one — the service is named in the link text, which is enough. Adding
 * `#1DB954` here would also be constrained by the placement table in that
 * module, and buys nothing the label doesn't already say.
 *
 * **Shape.** Renders as a `PlaylistRow` inside the shared "listen" card, so it
 * has the same service/status/action anatomy as YouTube and Apple. Its status
 * line is a count like theirs; the unmatched tracks and the overflow link are
 * *nested beneath it*, because both are consequences of this service's gap
 * rather than peers of it.
 *
 * The overflow link is worded to name what is missing ("hear the missing song
 * on youtube") rather than "hear the rest". The old wording sat at the same
 * indent and weight as the YouTube row's own playlist link and named the same
 * service, which is what made the section confusing.
 */

/** A per-row link inside the unmatched list. Neutral at rest, amber on hover
 *  only — hover applies to one row at a time, so it never repeats. */
const ROW_LINK_CLASS =
  "font-mono text-sm text-ink underline underline-offset-[3px] transition-colors duration-150 hover:text-ink-link";
const NOTE_CLASS = "font-mono text-sm text-ink";

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

export function SpotifyPlaylist({ mixId, entryCount }: { mixId: string; entryCount?: number }) {
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

  const matched = entryCount !== undefined ? entryCount - unmatched.length : undefined;

  return (
    <PlaylistRow
      service="spotify"
      status={
        playlistUrl
          ? // The status slot answers "can I play this right now", in the same
            // shape as every other service — a count, not a complaint. What went
            // wrong is nested below, where it belongs.
            unmatched.length > 0
            ? // A gap, phrased as a count when the total is known. When it is
              // not, say how many are missing rather than falling back to "all
              // songs" — which would be an outright lie in exactly the case the
              // user most needs the truth.
              matched !== undefined
              ? `${matched} of ${entryCount} songs`
              : `${unmatched.length} missing`
            : entryCount !== undefined
              ? // Phrased exactly as the YouTube row phrases it, so the three
                // statuses are directly comparable rather than merely similar.
                `all ${entryCount} songs`
              : "all songs"
          : inProgress
            ? "building…"
            : "not built yet"
      }
      action={
        playlistUrl ? (
          <PlaylistLink href={playlistUrl} label="open playlist in spotify">
            <MusicNoteIcon />
            open playlist
          </PlaylistLink>
        ) : null
      }
    >
      {unmatched.length > 0 ? (
        <>
          <ul className="space-y-1">
            {unmatched.map((track) => (
              <li key={track.submission_id} className={NOTE_CLASS}>
                {track.title} · {track.artist}
                <span className="text-ink-muted"> — {reasonLabel(track)}</span>
                {track.source_url ? (
                  <>
                    {" "}
                    <a
                      href={track.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={ROW_LINK_CLASS}
                    >
                      listen on {track.source}
                    </a>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
          {overflowYoutubeUrl ? (
            // Worded so it can never be mistaken for the YouTube row's own
            // playlist link. The old copy — "hear the rest on youtube" — sat at
            // the same indent and weight as that link a few rows above, and
            // named the same service, which is what made the section confusing.
            <div className="mt-2">
              <PlaylistLink
                href={overflowYoutubeUrl}
                label="hear the songs missing from spotify, on youtube"
              >
                <MusicNoteIcon />
                {unmatched.length === 1
                  ? "hear the missing song on youtube"
                  : `hear the ${unmatched.length} missing songs on youtube`}
              </PlaylistLink>
            </div>
          ) : null}
        </>
      ) : null}
    </PlaylistRow>
  );
}
