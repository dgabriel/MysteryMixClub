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
 * Per-player Apple Music playlist for a mix (MYS-108).
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

/**
 * True on a mobile OS with a native Apple Music app — where a direct
 * library-playlist link dead-ends with "Item Not Available" (MYS-190). The
 * desktop web player resolves that same link fine (MYS-214), so this is the
 * one thing that decides which URL {@link AppleMusicPlaylist} renders.
 *
 * iPadOS's Safari reports as "Macintosh" in its user-agent string (Apple
 * dropped the iPad identifier to unify with desktop Safari around iOS 13),
 * so a multi-touch "Mac" is treated as an iPad, not a real desktop.
 */
function isAppleMobileOS(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  const isKnownMobile = /iPhone|iPad|iPod|Android/.test(ua);
  const isIPadReportingAsMac = /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
  return isKnownMobile || isIPadReportingAsMac;
}

export function AppleMusicPlaylist({ mixId }: { mixId: string }) {
  // undefined = still loading, null = not configured / unavailable
  const [developerToken, setDeveloperToken] = useState<string | null | undefined>(undefined);
  const [playlistUrl, setPlaylistUrl] = useState<string | null | undefined>(undefined);
  const [directPlaylistUrl, setDirectPlaylistUrl] = useState<string | null>(null);
  const [playlistName, setPlaylistName] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Computed once — the OS doesn't change mid-session.
  const [isMobile] = useState(isAppleMobileOS);

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
    getApplePlaylistLink(mixId)
      .then((r) => {
        if (!active) return;
        setPlaylistUrl(r.playlist_url);
        setDirectPlaylistUrl(r.direct_playlist_url);
        setPlaylistName(r.playlist_name);
      })
      .catch(() => {
        if (active) setPlaylistUrl(null);
      });
    return () => {
      active = false;
    };
  }, [mixId]);

  async function handleGenerate() {
    if (!developerToken) return;
    setBusy(true);
    setError(null);
    try {
      // Apple's popup must open from the click, so authorize before any await
      // on our own API.
      const musicUserToken = await authorizeAppleMusic(developerToken);
      const result = await createApplePlaylist(mixId, musicUserToken);
      setPlaylistUrl(result.playlist_url);
      setDirectPlaylistUrl(result.direct_playlist_url);
      setPlaylistName(result.playlist_name);
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

  // Desktop's web player resolves a direct playlist link; iOS/Android's native
  // app dead-ends on the same URL with "Item Not Available" (MYS-190), so
  // mobile gets the Library root instead and has to make the last hop itself —
  // the playlist name is how they find it (MYS-214).
  const opensExactPlaylist = !isMobile && !!directPlaylistUrl;
  const targetUrl = opensExactPlaylist ? directPlaylistUrl : playlistUrl;

  return (
    <div className="mb-8">
      {targetUrl ? (
        <>
          <a href={targetUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
            <MusicNoteIcon />
            {opensExactPlaylist ? "open in apple music" : "open apple music library"}
          </a>
          {opensExactPlaylist ? (
            playlistName ? (
              <p className={NOTE_CLASS}>
                opens <span className="text-ink">“{playlistName}”</span> directly
              </p>
            ) : null
          ) : (
            <p className={NOTE_CLASS}>
              {playlistName ? (
                <>
                  go to your Apple Music playlists and look for{" "}
                  <span className="text-ink">“{playlistName}”</span>
                </>
              ) : (
                "go to your Apple Music playlists to find it"
              )}
            </p>
          )}
        </>
      ) : (
        <>
          <button type="button" onClick={handleGenerate} disabled={busy} className={BUTTON_CLASS}>
            <MusicNoteIcon />
            {busy ? "building playlist…" : "build this mystery mix in Apple Music"}
          </button>
          <p className={NOTE_CLASS}>(requires apple music subscription)</p>
        </>
      )}
      {error ? <p className={NOTE_CLASS}>{error}</p> : null}
    </div>
  );
}
