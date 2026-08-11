import { useEffect, useState } from "react";
import { Button } from "./Button";
import { MusicNoteIcon } from "./MusicNoteIcon";
import { PlaylistRow } from "./playlists/PlaylistRow";
import { ServiceMark } from "./playlists/ServiceMark";
import { PlaylistLink, PlaylistButton } from "./playlists/PlaylistAction";
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
 * Also lists any submissions that didn't make the playlist (`unmatched`,
 * MYS-201/GH-232). Unlike Spotify's read-only link, this is only known once
 * this player has generated their own copy — `getApplePlaylistLink` (the
 * read-only check on mount) doesn't return it, only `createApplePlaylist`'s
 * result does — so the list stays empty until `handleGenerate` succeeds.
 *
 * **No Apple Music red anywhere.** Third-party brand values live in
 * `lib/platformBrand.ts`, not in the theme, and this component has never used
 * one — the service is named in the link text, which is enough. `#FC3C44`
 * isn't even in that module yet, and adding it would buy nothing the label
 * doesn't already say while inheriting the module's placement constraint.
 *
 * **Where the amber goes.** The one whole-playlist action — build it, or open
 * it once built — and nothing else. The per-track "listen on …" links in the
 * unmatched list stay neutral: that list is one row per unmatched submission
 * and unbounded, so an accent there would repeat down the list and become
 * amber as pattern.
 */

/** The whole-playlist action link — the `link` button variant as an anchor. */
/** Same treatment on a <button>. Disabled drops the box entirely — no
 *  underline, label to `muted-foreground` — rather than fading it, matching
 *  the `Button` primitive. `disabled:` is emitted after `hover:` by Tailwind,
 *  so a disabled control can't pick up the hover color. */
/** A per-row link inside the unmatched list. Neutral at rest, amber on hover
 *  only — hover applies to one row at a time, so it never repeats. */
const ROW_LINK_CLASS =
  "font-mono text-sm text-ink underline underline-offset-[3px] transition-colors duration-150 hover:text-ink-link";
const NOTE_CLASS = "font-mono text-sm text-ink-muted";

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

export function AppleMusicPlaylist({ mixId, entryCount }: { mixId: string; entryCount?: number }) {
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

  const matched = entryCount !== undefined ? entryCount - unmatched.length : undefined;

  return (
    <PlaylistRow
      service="apple music"
      mark={<ServiceMark service="appleMusic" />}
      status={
        targetUrl
          ? unmatched.length > 0
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
          : busy
            ? "building…"
            : // Apple is the one service with no shareable link — it builds into
              // your own library — so its status says what it will do rather than
              // what exists. Keeping the sentence in the same slot is what lets the
              // difference read as meaning instead of inconsistency.
              "builds in your library"
      }
      action={
        targetUrl ? (
          <PlaylistLink
            href={targetUrl}
            label={
              opensExactPlaylist ? "open playlist in apple music" : "open your apple music library"
            }
          >
            <MusicNoteIcon />
            {opensExactPlaylist ? "open playlist" : "open library"}
          </PlaylistLink>
        ) : (
          <PlaylistButton
            onClick={() => setShowSignInModal(true)}
            disabled={busy}
            label="build this playlist in apple music"
          >
            <MusicNoteIcon />
            {busy ? "building…" : "build playlist"}
          </PlaylistButton>
        )
      }
    >
      {!targetUrl ? <p className={NOTE_CLASS}>needs an apple music subscription</p> : null}
      {targetUrl && !opensExactPlaylist ? (
        <p className={NOTE_CLASS}>
          {playlistName ? (
            <>
              find <span className="text-ink">“{playlistName}”</span> in your playlists
            </>
          ) : (
            "find it in your Apple Music playlists"
          )}
        </p>
      ) : null}
      {error ? <p className={NOTE_CLASS}>{error}</p> : null}
      {unmatched.length > 0 ? (
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
      ) : null}
      {/* The reassurance interstitial is a modal, so it sits at the top of the
          surface ladder: a `sheet` (Z4) panel wearing `shadow-z4`, whose 1px
          white ring IS the token — no border alongside it. `muted-foreground`
          fails AA on `sheet`, so every string here is `foreground`. */}
      {showSignInModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-floor/80 px-4">
          <div className="w-full max-w-sm rounded-tile bg-sheet px-6 py-5 shadow-z4">
            <p className="text-sm leading-[1.72] text-foreground">
              opens apple&apos;s own sign-in. we never see or store your apple id password.
            </p>
            <p className="mt-3 text-sm leading-[1.72] text-foreground">
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
    </PlaylistRow>
  );
}
