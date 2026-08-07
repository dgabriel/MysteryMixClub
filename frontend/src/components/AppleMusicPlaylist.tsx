import { useEffect, useState } from "react";
import { Button } from "./Button";
import { MusicNoteIcon } from "./MusicNoteIcon";
import {
  ApiError,
  createApplePlaylist,
  getAppleDeveloperToken,
  getApplePlaylistLink,
  type UnmatchedTrack,
} from "../services/api";
import { authorizeAppleMusic } from "../services/musickit";

// Human-readable reason text (MYS-201): `source_only` tracks were never in
// any streaming catalog to begin with, `no_catalog_match` tracks are catalog
// tracks Apple Music's search just couldn't resolve.
function reasonLabel(track: UnmatchedTrack): string {
  return track.reason === "source_only" ? "not on apple music" : "not found on apple music";
}

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
 *
 * Also lists any submissions that didn't make the playlist (`unmatched`,
 * MYS-201/GH-232). Unlike Spotify's read-only link, this is only known once
 * this player has generated their own copy — `getApplePlaylistLink` (the
 * read-only check on mount) doesn't return it, only `createApplePlaylist`'s
 * result does — so the list stays empty until `handleGenerate` succeeds.
 */

const LINK_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";
const BUTTON_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:cursor-default disabled:text-muted disabled:no-underline";
const NOTE_CLASS = "font-mono text-[13px] font-light text-muted";

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
  const [unmatched, setUnmatched] = useState<UnmatchedTrack[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSignInModal, setShowSignInModal] = useState(false);
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
    setShowSignInModal(false);
    setBusy(true);
    setError(null);
    try {
      // Apple's popup must open from the click, so authorize before any await
      // on our own API. Called from the modal's own "continue" button, which
      // is itself a fresh user gesture — the popup-blocker-safe requirement
      // survives the extra step.
      const musicUserToken = await authorizeAppleMusic(developerToken);
      const result = await createApplePlaylist(mixId, musicUserToken);
      setPlaylistUrl(result.playlist_url);
      setDirectPlaylistUrl(result.direct_playlist_url);
      setPlaylistName(result.playlist_name);
      setUnmatched(result.unmatched);
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
          <button
            type="button"
            onClick={() => setShowSignInModal(true)}
            disabled={busy}
            className={BUTTON_CLASS}
          >
            <MusicNoteIcon />
            {busy ? "building playlist…" : "build this mystery mix in Apple Music"}
          </button>
          <p className={NOTE_CLASS}>(requires apple music subscription)</p>
        </>
      )}
      {error ? <p className={NOTE_CLASS}>{error}</p> : null}
      {unmatched.length > 0 ? (
        <div className="mt-2">
          <p className={NOTE_CLASS}>
            {unmatched.length} {unmatched.length === 1 ? "song didn't" : "songs didn't"} make the
            apple music playlist:
          </p>
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
      {showSignInModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
          <div className="w-full max-w-sm border border-border bg-cream p-6">
            <p className="font-mono text-[13px] font-light text-ink">
              opens apple&apos;s own sign-in. we never see or store your apple id password.
            </p>
            <p className="mt-3 font-mono text-[13px] font-light text-ink">
              before you sign in, check that the page&apos;s address reads apple.com.
            </p>
            <div className="mt-6 flex gap-4">
              <Button type="button" onClick={handleGenerate}>
                continue to apple music
              </Button>
              <Button type="button" variant="ghost" onClick={() => setShowSignInModal(false)}>
                cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
