import { useEffect, useState } from "react";
import { MusicNoteIcon } from "./MusicNoteIcon";
import {
  ApiError,
  createApplePlaylist,
  getAppleDeveloperToken,
  getApplePlaylistLink,
} from "../services/api";
import { authorizeAppleMusic } from "../services/musickit";

/**
 * Per-player Apple Music playlist for a round (MYS-108).
 *
 * Unlike the Spotify link — one shared, public playlist any member can open —
 * Apple library playlists cannot be made public (MYS-107), so each member
 * generates their own copy into their own library. That means this component
 * both triggers generation and shows the result, and the link it renders is
 * personal: it opens only for the user who made it.
 *
 * Renders nothing at all when Apple Music isn't configured on the deployment,
 * so an unconfigured environment shows no dead option.
 *
 * Stays in the Sage/Ink family — no Rust: on the voting screen that single
 * signal belongs to the selected song.
 */

const LINK_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";
const BUTTON_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:cursor-default disabled:text-muted disabled:no-underline";
const NOTE_CLASS = "font-mono text-[11px] font-light text-muted";

export function AppleMusicPlaylist({ roundId }: { roundId: string }) {
  // undefined = still loading, null = not configured / unavailable
  const [developerToken, setDeveloperToken] = useState<string | null | undefined>(undefined);
  const [playlistUrl, setPlaylistUrl] = useState<string | null | undefined>(undefined);
  const [playlistName, setPlaylistName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unmatched, setUnmatched] = useState<number>(0);

  useEffect(() => {
    let active = true;
    getAppleDeveloperToken()
      .then((r) => {
        if (active) setDeveloperToken(r.token);
      })
      .catch(() => {
        if (active) setDeveloperToken(null);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    getApplePlaylistLink(roundId)
      .then((r) => {
        if (!active) return;
        setPlaylistUrl(r.playlist_url);
        setPlaylistName(r.playlist_name);
      })
      .catch(() => {
        if (active) setPlaylistUrl(null);
      });
    return () => {
      active = false;
    };
  }, [roundId]);

  async function handleGenerate() {
    if (!developerToken) return;
    setBusy(true);
    setError(null);
    try {
      // Apple's popup must open from the click, so authorize before any await
      // on our own API.
      const musicUserToken = await authorizeAppleMusic(developerToken);
      const result = await createApplePlaylist(roundId, musicUserToken);
      setPlaylistUrl(result.playlist_url);
      setPlaylistName(result.playlist_name);
      setUnmatched(result.total_count - result.track_count);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("apple music connection expired. try again.");
      } else if (err instanceof ApiError && err.status === 503) {
        setError("apple music isn't available right now.");
      } else {
        setError("couldn't build the playlist. try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  // Still loading, or Apple isn't configured — render nothing rather than a
  // flash of a control that may not apply.
  if (developerToken === undefined || playlistUrl === undefined) return null;
  if (developerToken === null) return null;

  return (
    <div className="mb-8">
      {playlistUrl ? (
        <>
          <a href={playlistUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
            <MusicNoteIcon />
            open apple music library
          </a>
          {/* The playlist is named rather than linked: iOS can't deep-link to a
              library playlist and dead-ends on "Item Not Available" (MYS-190).
              Older rows have no recorded name, so fall back to a plain note. */}
          <p className={NOTE_CLASS}>
            {playlistName ? (
              <>
                in your library as <span className="text-ink">“{playlistName}”</span>
              </>
            ) : (
              "in your library"
            )}
            {unmatched > 0 ? ` · ${unmatched} not on apple music` : ""}
          </p>
        </>
      ) : (
        <>
          <button type="button" onClick={handleGenerate} disabled={busy} className={BUTTON_CLASS}>
            <MusicNoteIcon />
            {busy ? "building playlist…" : "build this round in Apple Music"}
          </button>
          <p className={NOTE_CLASS}>(requires apple music subscription)</p>
        </>
      )}
      {error ? <p className={NOTE_CLASS}>{error}</p> : null}
    </div>
  );
}
