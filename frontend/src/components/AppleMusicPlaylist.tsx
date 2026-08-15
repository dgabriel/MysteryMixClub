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
import { AppleMusicError, authorizeAppleMusic, preloadAppleMusic } from "../services/musickit";

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
 * result does. Spotify can recompute its gap on read from each submission's
 * cached `spotify_track_uri`; Apple can't, because matching is per-user and
 * per-storefront, so there is no shared cached column to read back.
 *
 * That makes "we don't know the gap" a real state, and it is tracked as one:
 * `unmatched` is `null` until a generate result arrives, distinct from `[]`
 * for a playlist measured and found complete. The status line must never
 * collapse the two — reporting "all N songs" off an unmeasured playlist is
 * what MysteryMixClub-sdfd was, and it contradicted the "songs that may not be
 * on all playlists" list rendered directly beneath it on the same screen.
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
const NOTE_CLASS = "font-mono text-sm text-ink-muted";

// Apple Music's own home page — a generic, always-resolvable destination for
// mobile (MysteryMixClub-ap25). Deliberately not a specific resource: MYS-190's
// `/library` and MYS-214/o3r8's `/library/playlist/{id}` were both tried on
// mobile and both failed — the bare library link 404s, and the direct
// playlist link shows "Item Not Available" even opened via the native Music
// app's own `music://` scheme (so it's not a Safari-session or Universal
// Links problem; the specific library resource just doesn't resolve for a
// mobile client). Desktop's web player resolves the direct link fine and is
// unaffected by any of this — see `opensExactPlaylist` below.
const APPLE_MUSIC_HOME_URL = "https://music.apple.com";

/**
 * True on a mobile OS with a native Apple Music app, where the direct
 * library-playlist link cannot be trusted (MysteryMixClub-ap25 — see
 * `APPLE_MUSIC_HOME_URL` above).
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
  // Computed once — the OS doesn't change mid-session.
  const [isMobile] = useState(isAppleMobileOS);
  // undefined = still loading, null = not configured / unavailable
  const [developerToken, setDeveloperToken] = useState<string | null | undefined>(undefined);
  const [playlistUrl, setPlaylistUrl] = useState<string | null | undefined>(undefined);
  const [directPlaylistUrl, setDirectPlaylistUrl] = useState<string | null>(null);
  const [playlistName, setPlaylistName] = useState<string | null>(null);
  // null = the gap is unknown on this render, [] = known and genuinely complete.
  // The distinction is the whole fix for MysteryMixClub-sdfd: Apple's gap is only
  // ever reported by `createApplePlaylist`, so on a plain page load we have a
  // playlist link and no idea what is on it. Defaulting to [] made the status
  // read "all N songs" — completeness asserted from absence of data.
  const [unmatched, setUnmatched] = useState<UnmatchedTrack[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSignInModal, setShowSignInModal] = useState(false);

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

  // Warm Apple's SDK while the interstitial is on screen (MysteryMixClub-ljl5).
  // Loading and configuring MusicKit is the slow half, and doing it *after* the
  // tap cost the user activation that mobile Safari requires to open the
  // sign-in window — so the window never opened and the row hung on "building…".
  // The interstitial is two sentences the user has to read, which is exactly the
  // head start this needs. Failure is swallowed here on purpose: they have not
  // asked for anything yet, and handleGenerate reports it if they go on.
  useEffect(() => {
    if (!showSignInModal || !developerToken) return;
    preloadAppleMusic(developerToken).catch(() => {});
  }, [showSignInModal, developerToken]);

  async function handleGenerate() {
    if (!developerToken) return;
    setShowSignInModal(false);
    setBusy(true);
    setError(null);
    try {
      // Apple's sign-in window must open from the click, so authorize before any
      // await on our own API. Called from the modal's own "continue" button,
      // which is itself a fresh user gesture. The preload above is what makes
      // that gesture survive: warm, authorizeAppleMusic reaches Apple's
      // authorize() with nothing awaited in front of it.
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
      } else if (err instanceof AppleMusicError && err.kind === "sdk_blocked") {
        // Almost always a content blocker or Private Relay eating Apple's
        // script. Naming the likely cause is the difference between a dead end
        // and something the user can actually go and fix.
        setError("couldn't load apple music. a content or ad blocker may be blocking it.");
      } else if (err instanceof AppleMusicError && err.kind === "authorize_failed") {
        setError("apple's sign-in didn't finish. try again, and allow the window if asked.");
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

  // MYS-190, MYS-214, and MysteryMixClub-o3r8 each tried a different mobile
  // link (bare `/library`, then the direct playlist link) and each was
  // believed fixed on the strength of one on-device test that didn't hold up
  // on a fresh link-account-and-generate session. MysteryMixClub-ap25 settled
  // it: on mobile, always send the member to Apple Music's own home page and
  // tell them the playlist's name so they can find it themselves. Desktop is
  // unaffected — its web player has resolved the direct playlist link
  // reliably since MYS-214, and nothing here changes that path.
  const opensExactPlaylist = !isMobile && !!directPlaylistUrl;
  const hasPlaylist = playlistUrl != null;
  const targetUrl = !hasPlaylist
    ? null
    : isMobile
      ? APPLE_MUSIC_HOME_URL
      : (directPlaylistUrl ?? playlistUrl);
  const actionLabel = opensExactPlaylist
    ? "open playlist in apple music"
    : isMobile
      ? "open the apple music app"
      : "open your apple music library";
  const actionText = opensExactPlaylist
    ? "open playlist"
    : isMobile
      ? "open apple music"
      : "open library";

  const matched =
    unmatched !== null && entryCount !== undefined ? entryCount - unmatched.length : undefined;

  return (
    <PlaylistRow
      service="apple music"
      mark={<ServiceMark service="appleMusic" />}
      status={
        targetUrl
          ? unmatched === null
            ? // The playlist exists but this render never learned what is on it
              // (the read endpoint returns only the link). Say what we can stand
              // behind — it is in your library — rather than claiming a
              // completeness we did not measure. Persisting the gap so a revisit
              // can report it properly is MysteryMixClub-01u3.
              "in your library"
            : unmatched.length > 0
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
          <PlaylistLink href={targetUrl} label={actionLabel}>
            <MusicNoteIcon />
            {actionText}
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
              find <span className="text-ink">“{playlistName}”</span> in your library
            </>
          ) : (
            "find it in your Apple Music library"
          )}
        </p>
      ) : null}
      {error ? <p className={NOTE_CLASS}>{error}</p> : null}
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
