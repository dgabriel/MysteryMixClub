import { useEffect, useState } from "react";
import {
  ApiError,
  connectSpotify,
  createSpotifyPlaylist,
  getSpotifyStatus,
  type SpotifyPlaylistResult,
  type SpotifyStatus,
} from "../services/api";

/**
 * "Make a Spotify playlist of this mix" affordance for a round (MYS-83).
 *
 * Self-contained: fetches its own connect status on mount and renders nothing
 * unless the server has Spotify configured — so the feature stays invisible
 * until credentials exist. Three states:
 *   - not connected → a quiet "connect spotify" action that redirects to consent
 *   - connected     → a "generate spotify playlist" action
 *   - done          → an "open playlist in Spotify" link + how much of the mix
 *                     made it across, and anything that couldn't be matched.
 *
 * Stays firmly in the Sage/Ink family — a sage underline-style action mirroring
 * the YouTube link. No Rust: on the voting screen that single signal is reserved
 * for the selected song; errors use ink like the rest of this page.
 */

const ACTION_CLASS =
  "font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50 disabled:cursor-not-allowed";
const META_CLASS = "mt-1 block font-mono uppercase tracking-label text-[9px] text-muted";

export function SpotifyPlaylist({ roundId, entryCount }: { roundId: string; entryCount: number }) {
  const [status, setStatus] = useState<SpotifyStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<SpotifyPlaylistResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    // Best-effort: if status can't load, the feature simply stays hidden.
    getSpotifyStatus()
      .then((s) => {
        if (active) setStatus(s);
      })
      .catch(() => {
        if (active) setStatus({ configured: false, connected: false });
      });
    return () => {
      active = false;
    };
  }, []);

  if (!status || !status.configured) return null;

  async function handleConnect() {
    setBusy(true);
    setError(null);
    try {
      // Tell the backend to land us back on this round after consent (MYS-93).
      const { authorize_url } = await connectSpotify(`/rounds/${roundId}`);
      // Hand off to Spotify's consent page; the callback returns to the app.
      window.location.assign(authorize_url);
    } catch (err) {
      setBusy(false);
      setError(messageFor(err));
    }
  }

  async function handleGenerate() {
    setBusy(true);
    setError(null);
    try {
      setResult(await createSpotifyPlaylist(roundId));
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-8">
      {!status.connected ? (
        <button type="button" onClick={handleConnect} disabled={busy} className={ACTION_CLASS}>
          connect spotify to make a playlist
        </button>
      ) : result ? (
        <SpotifyResult result={result} entryCount={entryCount} />
      ) : (
        <button type="button" onClick={handleGenerate} disabled={busy} className={ACTION_CLASS}>
          {busy ? "creating playlist…" : "make a spotify playlist"}
        </button>
      )}
      {error ? (
        <p role="alert" className="mt-1 font-mono text-[11px] text-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function SpotifyResult({
  result,
  entryCount,
}: {
  result: SpotifyPlaylistResult;
  entryCount: number;
}) {
  if (!result.playlist_url) {
    return (
      <p className="font-mono text-[11px] font-light text-muted">
        none of these tracks were on Spotify.
      </p>
    );
  }
  return (
    <>
      <a
        href={result.playlist_url}
        target="_blank"
        rel="noopener noreferrer"
        className={ACTION_CLASS}
      >
        open playlist in Spotify
      </a>
      <span className={META_CLASS}>
        {result.track_count} of {entryCount} on Spotify
        {result.unmatched.length > 0 ? ` · ${result.unmatched.length} couldn't be matched` : ""}
      </span>
    </>
  );
}

function messageFor(err: unknown): string {
  // Surface the backend's calm detail (e.g. reconnect prompts) when present.
  if (err instanceof ApiError && err.message) return err.message;
  return "that didn't work. try again.";
}
