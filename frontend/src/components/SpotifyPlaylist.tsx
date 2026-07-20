import { useEffect, useState } from "react";
import { MusicNoteIcon } from "./MusicNoteIcon";
import { PlaylistGap } from "./PlaylistGap";
import { getSpotifyPlaylistLink, type UnmatchedTrack } from "../services/api";

/**
 * Read-only Spotify playlist link for a round (MYS-83, MYS-169).
 *
 * Generation is platform-admin only (a dedicated admin-screen action) — this
 * component never triggers it, only reads whatever link the admin already
 * produced. Self-contained: fetches its own link on mount and renders either
 * the link or a quiet "no spotify playlist yet" note. No busy/error states —
 * a failed fetch degrades to the same "not yet" note as "nothing generated".
 *
 * Stays firmly in the Sage/Ink family — a sage underline-style link mirroring
 * the YouTube link. No Rust: on the voting screen that single signal is reserved
 * for the selected song.
 */

const LINK_CLASS =
  "inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";
const NOTE_CLASS = "font-mono text-[11px] font-light text-muted";

export function SpotifyPlaylist({ roundId }: { roundId: string }) {
  const [playlistUrl, setPlaylistUrl] = useState<string | null | undefined>(undefined);
  const [unmatched, setUnmatched] = useState<UnmatchedTrack[]>([]);

  useEffect(() => {
    let active = true;
    getSpotifyPlaylistLink(roundId)
      .then((r) => {
        if (!active) return;
        setPlaylistUrl(r.playlist_url);
        setUnmatched(r.unmatched);
      })
      .catch(() => {
        if (active) setPlaylistUrl(null);
      });
    return () => {
      active = false;
    };
  }, [roundId]);

  // undefined = still loading; render nothing rather than a flash of the note.
  if (playlistUrl === undefined) return null;

  return (
    <div className="mb-8">
      {playlistUrl ? (
        <>
          <PlaylistGap unmatched={unmatched} />
          <a href={playlistUrl} target="_blank" rel="noopener noreferrer" className={LINK_CLASS}>
            <MusicNoteIcon />
            open playlist in Spotify
          </a>
        </>
      ) : (
        <p className={NOTE_CLASS}>no spotify playlist yet</p>
      )}
    </div>
  );
}
