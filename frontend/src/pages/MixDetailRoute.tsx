import { type FormEvent, type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  addNote,
  castVotes,
  deleteSubmission,
  editNote,
  editSubmission,
  extendVotingDeadline,
  getClub,
  getClubMembers,
  getMyMembership,
  getMySubmissions,
  getMyVotes,
  getNotes,
  getPlaylist,
  getResults,
  getMix,
  getVoteCounts,
  submitSong,
  updateMix,
  updateSubmissionNote,
  type Club,
  type LeaderboardEntry,
  type ClubMember,
  type MostNotedWinner,
  type Note,
  type PlatformKey,
  type PlaylistEntry,
  type ResolvedSong,
  type ResultNote,
  type ResultSubmission,
  type Mix,
  type MixResults,
  type RevealPick,
  type MixState,
  type SubmissionInput,
  type SubmissionResult,
  type VoteCountEntry,
  type WinnerReveal,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { usePolling } from "../hooks/usePolling";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { PaperSurface } from "../components/PaperSurface";
import { PaperSectionHeading } from "../components/PaperSectionHeading";
import { PlaylistRow } from "../components/playlists/PlaylistRow";
import { ServiceMark } from "../components/playlists/ServiceMark";
import { PlaylistsSection } from "../components/playlists/PlaylistsSection";
import { PlaylistLink } from "../components/playlists/PlaylistAction";
import { MIX_BADGE, MIX_STATE_LABEL, mixGroup } from "../utils/mixState";
import { TextField } from "../components/TextField";
import { FormError } from "../components/FormError";
import { ConcentricRings } from "../components/ConcentricRings";
import { SongSearchCard } from "../components/songs/SongSearchCard";
import { SourceBadge } from "../components/SourceBadge";
import { AppleMusicPlaylist } from "../components/AppleMusicPlaylist";
import { SpotifyPlaylist } from "../components/SpotifyPlaylist";
import {
  SongsMaybeMissing,
  type MaybeMissingTrack,
} from "../components/playlists/SongsMaybeMissing";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { CrownIcon } from "../components/CrownIcon";
import { MedalIcon } from "../components/MedalIcon";
import { MusicNoteIcon } from "../components/MusicNoteIcon";
import { DeadlineChip } from "../components/DeadlineChip";
import { HelpLink } from "../components/HelpLink";
import { toDatetimeLocalValue } from "../utils/deadline";

/**
 * Announces mix.state transitions to screen readers (MYS-121) — the poll
 * that refreshes this data has no visual "page changed" cue of its own, so
 * without this a phase change (e.g. submissions -> voting) is silent to AT
 * users. Visually hidden; only fires on an actual state change, not on every
 * poll tick with an unchanged state.
 */
function MixStateAnnouncer({ state }: { state: MixState }) {
  const previous = useRef(state);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (previous.current !== state) {
      previous.current = state;
      setMessage(`this mystery mix is now ${MIX_STATE_LABEL[state]}`);
    }
  }, [state]);

  return (
    <p role="status" aria-live="polite" className="sr-only">
      {message}
    </p>
  );
}

const PLATFORM_LABELS: { key: string; label: string }[] = [
  { key: "spotify", label: "Spotify" },
  { key: "appleMusic", label: "Apple Music" },
  { key: "deezer", label: "Deezer" },
  { key: "youtube", label: "YouTube" },
  { key: "youtubeMusic", label: "YouTube Music" },
  { key: "bandcamp", label: "Bandcamp" },
];

/**
 * The inline text-button treatment used by the per-row controls on this
 * screen (change song, remove, note affordances, the notes disclosure).
 *
 * Neutral at rest with an amber *hover*, rather than the `link` Button
 * variant's resting amber. Every one of these buttons sits inside a repeated
 * card — one per submitted song, one per playlist entry, one per pick — so a
 * resting accent would appear once per row and read as the list's styling
 * rather than as a signal. Hover is transient and applies to one control at a
 * time, so it keeps the accent. Same treatment R10 landed on for
 * `ClubHomeScreen`'s per-member controls.
 *
 * Two weights, mirroring what these rows already distinguished: the primary
 * action of a row is `foreground`, its secondary/undo action is
 * `muted-foreground`. Disabled drops the underline and the label to
 * `muted-foreground` — never `opacity-50`.
 */
const ROW_ACTION_CLASS =
  "font-mono uppercase tracking-mono text-label text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline";
const ROW_ACTION_MUTED_CLASS =
  "font-mono uppercase tracking-mono text-label text-muted-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-foreground disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline";

/** Partial-submission leave-warning copy (MYS-250) — the submitted/cap count
 *  alone didn't convey the deadline pressure, so a deadline nudge replaces
 *  the closing question when the mix has an active submission deadline;
 *  falls back to the original phrasing when it doesn't. */
function leaveWarningMessage(mix: Mix, submitted: number, cap: number): string {
  const base = `you've submitted ${submitted} of ${cap} songs.`;
  if (!mix.submission_deadline) return `${base} leave anyway?`;
  const remaining = cap - submitted;
  const song = remaining === 1 ? "song" : "songs";
  return `${base} come back before the deadline to submit your final ${remaining} ${song}.`;
}

/**
 * Mix detail (`/mixes/:id`). State-aware:
 *  - open_submission → submit/replace your song (organizer can open voting)
 *  - open_voting     → the anonymous, shuffled playlist (organizer can close)
 *  - closed          → revealed submissions
 * Self-contained: loads the mix + club (for organizer/name) plus the
 * state-specific data, and wires submit / advance back to the API.
 */
export function MixDetailRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [mix, setMix] = useState<Mix | null>(null);
  const [club, setClub] = useState<Club | null>(null);
  // Club membership (MYS-99), fetched alongside club so co-organizers get
  // parity with the fixed organizer on mix-management controls (see isAdmin).
  const [members, setMembers] = useState<ClubMember[]>([]);
  const [mySubmissions, setMySubmissions] = useState<SubmissionResult[]>([]);
  // Per-mix "Casual Mode for this Mix" toggle (MYS-60), seeded from the
  // existing submission's mode, else the caller's per-club default.
  const [mixVibe, setMixVibe] = useState(false);
  const [playlist, setPlaylist] = useState<PlaylistEntry[]>([]);
  const [youtubePlaylistUrl, setYoutubePlaylistUrl] = useState<string | null>(null);
  const [youtubeTrackCount, setYoutubeTrackCount] = useState(0);
  // Voting progress (MYS-102): X of Y competitive mode voted or noted · Z casual mode.
  const [votingEligible, setVotingEligible] = useState(0);
  const [votingActed, setVotingActed] = useState(0);
  const [vibingCount, setVibingCount] = useState(0);
  const [myVotes, setMyVotes] = useState<string[]>([]);
  const [voteCounts, setVoteCounts] = useState<VoteCountEntry[]>([]);
  const [isVotesLocked, setIsVotesLocked] = useState(false);
  const [results, setResults] = useState<MixResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [clubRepeatWarning, setClubRepeatWarning] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [rollingBack, setRollingBack] = useState(false);
  const [extendingVoting, setExtendingVoting] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [casting, setCasting] = useState(false);
  const [votesSaved, setVotesSaved] = useState(false);

  const submissionCap = club?.songs_per_submission ?? 1;
  const partiallySubmitted =
    mix?.state === "open_submission" &&
    mySubmissions.length > 0 &&
    mySubmissions.length < submissionCap;

  const blocker = useBlocker(partiallySubmitted);

  useEffect(() => {
    if (!partiallySubmitted) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [partiallySubmitted]);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const loadedMix = await getMix(id);
      const [loadedClub, loadedMembers] = await Promise.all([
        getClub(loadedMix.club_id),
        getClubMembers(loadedMix.club_id),
      ]);
      setMix(loadedMix);
      setClub(loadedClub);
      setMembers(loadedMembers);

      if (loadedMix.state === "pending") {
        // Nothing to load yet — the mix isn't open. The organizer can edit its
        // theme/description and open it from here.
      } else if (loadedMix.state === "open_submission") {
        const [loadedMine, membership] = await Promise.all([
          getMySubmissions(id),
          getMyMembership(loadedMix.club_id),
        ]);
        setMySubmissions(loadedMine);
        // Seed the mix toggle: the player's current stance (uniform across
        // their songs) wins, else the member's per-club default.
        setMixVibe(
          loadedMine.length > 0
            ? loadedMine[0].participation_mode === "vibing"
            : membership.vibe_mode,
        );
      } else if (loadedMix.state === "open_voting") {
        const [loadedPlaylist, loadedVotes, loadedMine, loadedCounts, membership] =
          await Promise.all([
            getPlaylist(id),
            getMyVotes(id),
            getMySubmissions(id),
            getVoteCounts(id),
            getMyMembership(loadedMix.club_id),
          ]);
        setPlaylist(loadedPlaylist.entries);
        setYoutubePlaylistUrl(loadedPlaylist.youtube_playlist_url);
        setYoutubeTrackCount(loadedPlaylist.youtube_track_count);
        setVotingEligible(loadedPlaylist.voting_eligible);
        setVotingActed(loadedPlaylist.voting_acted);
        setVibingCount(loadedPlaylist.vibing_count);
        setMyVotes(loadedVotes.submission_ids);
        setVoteCounts(loadedCounts.entries);
        // Votes are locked if the player has already cast at least one vote
        setIsVotesLocked(loadedVotes.submission_ids.length > 0);
        setMySubmissions(loadedMine);
        // Seed the vibe stance for voting the same way submission does: the
        // player's per-mix stance (uniform across their songs) if they
        // submitted, else their per-club default — so a vibe-mode non-submitter
        // sits voting out instead of seeing a ballot the API rejects (MYS-167).
        setMixVibe(
          loadedMine.length > 0
            ? loadedMine[0].participation_mode === "vibing"
            : membership.vibe_mode,
        );
      } else {
        // Closed: the reveal plus a way to still listen to the mix (MYS-133).
        // The playlist endpoint serves closed mixes too.
        const [loadedResults, loadedPlaylist] = await Promise.all([
          getResults(id),
          getPlaylist(id),
        ]);
        setResults(loadedResults);
        setPlaylist(loadedPlaylist.entries);
        setYoutubePlaylistUrl(loadedPlaylist.youtube_playlist_url);
        setYoutubeTrackCount(loadedPlaylist.youtube_track_count);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "couldn't load this mystery mix.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll every 60s so state transitions (submission → voting → closed) and
  // progress counts update without a manual reload. Fetches only the mix on
  // each tick; triggers a full load() only when the state actually changes.
  usePolling(() => {
    if (!id) return;
    void (async () => {
      try {
        const refreshed = await getMix(id);
        if (refreshed.state !== mix?.state) {
          void load();
          return;
        }
        setMix(refreshed);
        if (refreshed.state === "open_voting") {
          try {
            const counts = await getVoteCounts(id);
            setVoteCounts(counts.entries);
          } catch {
            // non-fatal
          }
        }
      } catch {
        // non-fatal
      }
    })();
  });

  const isOrganizer = !!userId && !!club && club.organizer_id === userId;
  // Co-organizers (role === "admin") get parity with the fixed organizer on
  // mix-management controls (MYS-99) — same derivation as ClubHomeRoute.
  const ownMember = members.find((m) => m.user_id === userId);
  const isAdmin = isOrganizer || ownMember?.is_admin === true;

  // Refresh the mix so "X of Y submitted" reflects an add/remove right away
  // (MYS-101). Refetch rather than locally increment so a *replacement* (which
  // doesn't change the distinct-player count) stays correct too. Non-fatal: the
  // mutation already saved; only the counter would lag.
  const refreshCount = useCallback(async () => {
    if (!id) return;
    try {
      setMix(await getMix(id));
    } catch {
      // leave the counter as-is; the submission mutation itself succeeded.
    }
  }, [id]);

  function trackPayload(song: ResolvedSong): SubmissionInput {
    return {
      title: song.title,
      artist: song.artist ?? "",
      // Exactly one identity: a catalog isrc, or a source-only key (+ Bandcamp
      // track id when present) for a Bandcamp/YouTube pick (MYS-201).
      ...(song.source_key
        ? { source_key: song.source_key, bandcamp_track_id: song.bandcamp_track_id }
        : { isrc: song.isrc }),
      album: song.album,
      album_art_url: song.thumbnail_url,
      // The stance is uniform across all your songs; the backend propagates it.
      participation_mode: mixVibe ? "vibing" : "playing",
    };
  }

  async function handleAddSong(song: ResolvedSong, note: string | null): Promise<boolean> {
    if (!id || (!song.isrc && !song.source_key)) {
      setActionError("this song is missing an ID and can't be submitted.");
      return false;
    }
    setSubmitting(true);
    setActionError(null);
    setClubRepeatWarning(false);
    try {
      const result = await submitSong(id, { ...trackPayload(song), note });
      setMySubmissions((current) => [...current, result]);
      if (result.club_previously_submitted) setClubRepeatWarning(true);
      await refreshCount();
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.message.includes("already in this")) {
        setActionError(
          `"${song.title}" by ${song.artist} is already in this mystery mix — someone else has great taste too.`,
        );
      } else {
        setActionError(err instanceof ApiError ? err.message : "couldn't submit. try again.");
      }
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  async function handleEditSong(
    submissionId: string,
    song: ResolvedSong,
    note: string | null,
  ): Promise<boolean> {
    if (!id || (!song.isrc && !song.source_key)) {
      setActionError("this song is missing an ID and can't be submitted.");
      return false;
    }
    setSubmitting(true);
    setActionError(null);
    setClubRepeatWarning(false);
    try {
      const result = await editSubmission(id, submissionId, { ...trackPayload(song), note });
      // Replace the edited song, and keep the stance uniform across the list
      // (the backend applies an explicit mode change to every song).
      setMySubmissions((current) =>
        current.map((s) =>
          s.id === submissionId ? result : { ...s, participation_mode: result.participation_mode },
        ),
      );
      if (result.club_previously_submitted) setClubRepeatWarning(true);
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.message.includes("already in this")) {
        setActionError(
          `"${song.title}" by ${song.artist} is already in this mystery mix — someone else has great taste too.`,
        );
      } else {
        setActionError(
          err instanceof ApiError ? err.message : "couldn't save the change. try again.",
        );
      }
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemoveSong(submissionId: string): Promise<boolean> {
    if (!id) return false;
    setRemovingId(submissionId);
    setActionError(null);
    try {
      await deleteSubmission(id, submissionId);
      setMySubmissions((current) => current.filter((s) => s.id !== submissionId));
      await refreshCount();
      return true;
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "couldn't remove that song. try again.",
      );
      return false;
    } finally {
      setRemovingId(null);
    }
  }

  async function handleSaveNote(submissionId: string, note: string | null) {
    if (!id) return;
    try {
      const result = await updateSubmissionNote(id, submissionId, note);
      setMySubmissions((current) => current.map((s) => (s.id === submissionId ? result : s)));
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't save the note. try again.");
    }
  }

  async function handleCastVotes(selected: string[]) {
    if (!id || selected.length === 0) return;
    setCasting(true);
    setActionError(null);
    setVotesSaved(false);
    try {
      const result = await castVotes(id, selected);
      setMyVotes(result.submission_ids);
      setVotesSaved(true);
      // Refresh voting progress so "X of Y voted or noted" reflects this cast
      // right away (MYS-102). Non-fatal: the votes already saved.
      try {
        const refreshed = await getPlaylist(id);
        setVotingEligible(refreshed.voting_eligible);
        setVotingActed(refreshed.voting_acted);
        setVibingCount(refreshed.vibing_count);
        // Also fetch the updated vote counts so the player sees their impact
        const counts = await getVoteCounts(id);
        setVoteCounts(counts.entries);
        // Votes are now locked - can't change after casting
        setIsVotesLocked(true);
      } catch {
        // A 409 from vote-counts means the mix auto-advanced to closed because
        // this was the last voter (MYS-69). Re-fetch the mix and, if it's no
        // longer in voting, pull results so the final voter transitions straight
        // to the reveal instead of being stranded on a stale voting screen.
        try {
          const updatedMix = await getMix(id);
          setMix(updatedMix);
          if (updatedMix.state !== "open_voting") {
            setResults(await getResults(id));
          }
        } catch {
          // best-effort; the cast itself already succeeded.
        }
      }
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "couldn't save your votes. try again.",
      );
    } finally {
      setCasting(false);
    }
  }

  async function handleEditMix(input: { theme?: string | null; description?: string | null }) {
    if (!id) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const updated = await updateMix(id, input);
      setMix(updated);
      return true;
    } catch (err) {
      setEditError(
        err instanceof ApiError ? err.message : "couldn't save the mystery mix. try again.",
      );
      return false;
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleAdvance(next: MixState) {
    if (!id) return;
    setAdvancing(true);
    setActionError(null);
    try {
      await updateMix(id, { state: next });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't update the mystery mix.");
    } finally {
      // Reset on success too — otherwise the button sticks on "opening…" after
      // the mix has opened (MYS-95).
      setAdvancing(false);
    }
  }

  // Organizer: roll an open_voting mix back to open_submission (MYS-168) —
  // the one sanctioned backward step. Separate busy/error handling from
  // handleAdvance so the two organizer actions don't fight over one flag.
  async function handleRollback() {
    if (!id) return;
    setRollingBack(true);
    setActionError(null);
    try {
      await updateMix(id, { state: "open_submission" });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't reopen submissions.");
    } finally {
      setRollingBack(false);
    }
  }

  // Organizer: push voting to a chosen time, up to 48h out, without waiting for
  // it to close and reopening submissions (MYS-180) — the mix stays exactly
  // where it is. `localDatetime` is the raw <input type="datetime-local"> value
  // (browser-local, no timezone marker); Date() parses that as local time, so
  // toISOString() below correctly converts it to UTC for the API.
  async function handleExtendVoting(localDatetime: string) {
    if (!id) return;
    setExtendingVoting(true);
    setActionError(null);
    try {
      const updated = await extendVotingDeadline(id, new Date(localDatetime).toISOString());
      setMix(updated);
      return true;
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't extend voting.");
      return false;
    } finally {
      setExtendingVoting(false);
    }
  }

  if (loading) {
    return (
      <PaperSurface nested>
        <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
          <ConcentricRings size={88} spinning onPaper className="mx-auto" />
        </main>
      </PaperSurface>
    );
  }

  if (error || !mix || !id) {
    return (
      // A failed *load*, not a form error: the mix never resolved, so this is
      // the whole content of the screen rather than a message about a field.
      // ADR 0004's `destructive-text` category is for form validation, so this
      // stays plain `foreground` — matching ClubHomeScreen's error state.
      <PaperSurface nested>
        <main className="flex flex-1 flex-col items-center justify-center px-4 text-center sm:px-8">
          <p className="text-sm leading-[1.72] text-ink">{error ?? "mystery mix not found."}</p>
          <div className="mt-6">
            <Button variant="ghost" onPaper type="button" onClick={() => navigate("/home")}>
              home
            </Button>
          </div>
        </main>
      </PaperSurface>
    );
  }

  // Amber budget (category rule, not a count). Every amber on this screen is
  // an ACTION or an ACHIEVEMENT, and none of it is per-row on an unbounded
  // list:
  //  - ACTION: the organizer CTAs, the cast-votes CTA, the playlist/listen
  //    links, the `link`-variant text buttons, and hover/focus states.
  //  - ACTION (interactive state): a selected vote card. Bounded by
  //    `votes_per_player`, entirely user-driven, and the design system's own
  //    AlbumCard "guessed" state marks exactly this with amber.
  //  - ACHIEVEMENT: Most Noted and the Winner(s) — one section of each per
  //    mix.
  //  - ACTION: `DeadlineChip`, which grades its own urgency and goes amber
  //    only while the deadline is actually closing.
  // Dropped to neutral on purpose (see each component): the rank medals in the
  // picks list, the locked vote tally, the per-row source/platform/unmatched
  // links, submitter-note rules, and the "your submission" own-song card.
  // The shared TopNav is rendered by AuthedLayout, so this is content-only.
  return (
    <>
      {/* `useBlocker` renders in-app UI, not a native `window.confirm`, so this
          is a real modal and takes the top of the surface ladder: a `sheet`
          (Z4) panel wearing `shadow-z4`. That shadow token carries its own 1px
          white ring, so the panel deliberately has no `border`. `sheet` is the
          one surface `muted-foreground` fails on, so the copy is `foreground`. */}
      {blocker.state === "blocked" ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-floor/80 px-4">
          <div className="w-full max-w-sm rounded-tile bg-sheet px-6 py-5 shadow-z4">
            <p className="text-sm leading-[1.72] text-foreground">
              {leaveWarningMessage(mix, mySubmissions.length, submissionCap)}
            </p>
            <div className="mt-6 flex gap-4">
              <Button type="button" onClick={() => blocker.proceed()}>
                leave
              </Button>
              <Button type="button" variant="ghost" onClick={() => blocker.reset()}>
                stay
              </Button>
            </div>
          </div>
        </div>
      ) : null}
      {/* Content-only: the shared TopNav is rendered once by AuthedLayout. The
        mix's club is reached via a named link above the title (not a generic
        "← club" in the nav), so members always see which club they're in. */}
      <PaperSurface nested>
        <main className="mx-auto w-full max-w-lg px-4 pt-8 pb-16 sm:px-8">
          {club ? (
            <button
              type="button"
              onClick={() => navigate(`/clubs/${mix.club_id}`)}
              className="inline-flex items-center gap-1.5 font-mono uppercase tracking-mono text-label text-ink transition-colors duration-150 hover:text-ink-accent"
            >
              <span aria-hidden="true">←</span>
              {club.name}
            </button>
          ) : null}
          {/* The mix number in the accent, matching the club page's mix rows.
            `ink-accent` because this sits on paper — plain `accent` is 2.62:1
            there. */}
          <span className="mt-3 block font-mono uppercase tracking-mono-caps text-mini text-ink-accent">
            mystery mix {mix.mix_number}
          </span>
          <div className="mt-1 flex items-start justify-between gap-4">
            <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
              {mix.theme ?? `Mystery Mix ${mix.mix_number}`}
            </h1>
            <div className="shrink-0 pt-2">
              {/* Same weight ladder as the club page's mix list: a solid green
                fill while the mix is live, a bright neutral for upcoming, quiet
                once it is done. */}
              <Badge variant={MIX_BADGE[mixGroup(mix.state)]}>{MIX_STATE_LABEL[mix.state]}</Badge>
            </div>
          </div>
          <MixStateAnnouncer state={mix.state} />
          {mix.description ? (
            <p className="mt-3 text-sm leading-[1.72] text-ink-muted">{mix.description}</p>
          ) : null}

          {/* Prominent, phase-appropriate deadline chip (MYS-161) — viewer-local
            time plus a live countdown. Renders nothing for legacy mixes with
            no deadline set. */}
          <DeadlineChip mix={mix} onPaper className="mt-4" showCountdown />

          {isAdmin ? (
            <>
              <OrganizerControls
                state={mix.state}
                hasTheme={!!mix.theme}
                advancing={advancing}
                onAdvance={handleAdvance}
                isFinalMix={!!club && mix.mix_number >= club.total_mixes}
                onRollback={handleRollback}
                rollingBack={rollingBack}
                votingDeadline={mix.voting_deadline}
                onExtendVoting={handleExtendVoting}
                extendingVoting={extendingVoting}
                totalVotes={voteCounts.reduce((sum, entry) => sum + entry.vote_count, 0)}
                casualClub={!!club?.default_vibe_mode}
              />
              <EditMixForm
                mix={mix}
                saving={savingEdit}
                error={editError}
                onSave={handleEditMix}
                onDismissError={() => setEditError(null)}
              />
            </>
          ) : null}

          {/* A failed mutation is a screen-level form error (ADR 0004) — its own
            color category, so it consumes nothing from this screen's amber. */}
          {actionError ? (
            <div className="mt-6">
              <FormError onPaper>{actionError}</FormError>
            </div>
          ) : null}
          {clubRepeatWarning && !actionError ? (
            <p className="mt-6 text-sm leading-[1.72] text-ink-muted">
              this song was submitted in a previous mystery mix — submitted anyway.
            </p>
          ) : null}

          <section className="mt-10">
            {mix.state === "pending" ? (
              <p className="text-sm leading-[1.72] text-ink-muted">
                this mystery mix hasn&apos;t opened yet.
              </p>
            ) : mix.state === "open_submission" ? (
              <>
                <SubmissionProgress submitted={mix.submission_count} total={mix.member_count} />
                <SubmissionManager
                  submissions={mySubmissions}
                  cap={club?.songs_per_submission ?? 1}
                  submitting={submitting}
                  removingId={removingId}
                  onAdd={handleAddSong}
                  onEdit={handleEditSong}
                  onRemove={handleRemoveSong}
                  onSaveNote={handleSaveNote}
                  onConfirm={() => navigate(`/clubs/${mix.club_id}`)}
                />
              </>
            ) : mix.state === "open_voting" ? (
              <VotingSection
                // Remount to re-seed the selection whenever the saved votes change.
                key={myVotes.join(",")}
                mixId={id}
                entries={playlist}
                voteCounts={voteCounts}
                isVotesLocked={isVotesLocked}
                youtubePlaylistUrl={youtubePlaylistUrl}
                youtubeTrackCount={youtubeTrackCount}
                votingEligible={votingEligible}
                votingActed={votingActed}
                vibingCount={vibingCount}
                votesPerPlayer={mix.votes_per_player}
                myVotes={myVotes}
                // A submitter's stance is their song's mode; a non-submitter falls
                // back to their club vibe flag so vibe-mode members sit out (MYS-167).
                isVibingParticipant={
                  mySubmissions.length > 0
                    ? mySubmissions[0].participation_mode === "vibing"
                    : mixVibe
                }
                casting={casting}
                votesSaved={votesSaved}
                onCast={handleCastVotes}
                onSelectionChange={() => setVotesSaved(false)}
                onActionError={setActionError}
              />
            ) : (
              <>
                {/* Closed mixes keep a way to listen to the mix (MYS-133). */}
                <ClosedListen
                  mixId={id}
                  youtubePlaylistUrl={youtubePlaylistUrl}
                  youtubeTrackCount={youtubeTrackCount}
                  entryCount={playlist.length}
                  sourceOnly={
                    results
                      ? toSourceOnly(results.viewer_is_vibing ? results.picks : results.submissions)
                      : []
                  }
                />
                <ResultsSection results={results} userId={userId} onActionError={setActionError} />
              </>
            )}
          </section>
        </main>
      </PaperSurface>
    </>
  );
}

function OrganizerControls({
  state,
  hasTheme,
  advancing,
  onAdvance,
  isFinalMix,
  onRollback,
  rollingBack,
  votingDeadline,
  onExtendVoting,
  extendingVoting,
  totalVotes,
  casualClub,
}: {
  state: MixState;
  hasTheme: boolean;
  advancing: boolean;
  onAdvance: (next: MixState) => void;
  isFinalMix: boolean;
  onRollback: () => void;
  rollingBack: boolean;
  votingDeadline: string | null;
  onExtendVoting: (localDatetime: string) => Promise<boolean | undefined>;
  extendingVoting: boolean;
  totalVotes: number;
  /** Club-wide casual mode (MYS-256) — no real competitive voting happens for
   *  an all-vibing club, so the open_submission → open_voting transition
   *  reads as revealing the mystery mix rather than "opening voting". Notes
   *  are unaffected either way — they're never gated by vibe mode. */
  casualClub: boolean;
}) {
  // Closing is the one forward transition that cascades and can't be undone
  // in-app (MYS-170) — gated behind an explicit second step. Opening the mix
  // / opening voting stay one-click; they're lower-risk and easy to reason
  // about.
  const [confirmingClose, setConfirmingClose] = useState(false);
  // The one sanctioned backward step (MYS-168) — same two-step treatment,
  // since it discards any votes already cast.
  const [confirmingRollback, setConfirmingRollback] = useState(false);
  // Extend voting to an organizer-chosen deadline, up to 48h past the current
  // one (MYS-180). Non-destructive (nothing is discarded), so no confirm copy
  // beyond the picker itself — but still a distinct step, since it needs the
  // input.
  const [extendingOpen, setExtendingOpen] = useState(false);
  const [chosenDeadline, setChosenDeadline] = useState("");
  // Collapsed by default. These are the only controls on the screen a member
  // never sees, and on a mix the organizer is only reading, they were three
  // rectangles competing with the mix itself. Tidied away, not removed — one
  // click brings the whole set back.
  const [toolsOpen, setToolsOpen] = useState(false);

  if (state === "closed") return null;
  const next: MixState =
    state === "pending"
      ? "open_submission"
      : state === "open_submission"
        ? "open_voting"
        : "closed";
  const label =
    state === "pending"
      ? "open mix"
      : state === "open_submission"
        ? casualClub
          ? "reveal the mystery mix"
          : "open mystery mix voting"
        : "close mix";
  const busyLabel =
    next === "closed"
      ? "closing…"
      : casualClub && next === "open_voting"
        ? "revealing…"
        : "opening…";
  const busy = advancing || rollingBack || extendingVoting;

  // Bounds for the extend picker: must be after the current deadline, and no
  // more than 48h past it (MYS-180) — mirrors the API's own validation so the
  // picker can't offer a value the server would reject.
  const currentDeadline = votingDeadline ? new Date(votingDeadline) : null;
  const minDatetime = currentDeadline
    ? toDatetimeLocalValue(new Date(currentDeadline.getTime() + 60_000))
    : undefined;
  const maxDatetime = currentDeadline
    ? toDatetimeLocalValue(new Date(currentDeadline.getTime() + 48 * 60 * 60 * 1000))
    : undefined;
  const defaultDeadline = currentDeadline
    ? toDatetimeLocalValue(new Date(currentDeadline.getTime() + 4 * 60 * 60 * 1000))
    : "";

  function openExtendPicker() {
    setChosenDeadline(defaultDeadline);
    setExtendingOpen(true);
  }

  async function handleSaveExtend() {
    if (!chosenDeadline) return;
    const ok = await onExtendVoting(chosenDeadline);
    if (ok) setExtendingOpen(false);
  }

  function toggleTools() {
    const next = !toolsOpen;
    // Collapsing abandons any half-finished step. Leaving a confirm armed
    // behind a closed panel would mean re-opening it lands on "yes, close mix"
    // rather than the row of tools you asked for.
    if (!next) {
      setConfirmingClose(false);
      setConfirmingRollback(false);
      setExtendingOpen(false);
    }
    setToolsOpen(next);
  }

  // A mix can't open without a theme (MYS-211) — block the click rather than
  // let the organizer hit the server's 409. Only applies to "open mix" itself;
  // once a mix is open its theme is already locked in, so nothing later in
  // the lifecycle needs this check.
  const blockedByMissingTheme = state === "pending" && !hasTheme;

  /** What sits inside the disclosure: a confirm step, the extend picker, or
   *  the tools themselves. Only one is ever showing. */
  function panel() {
    if (next === "closed" && confirmingClose) {
      return (
        <div className="space-y-4">
          <p className="text-sm leading-[1.72] text-ink-muted">
            {isFinalMix
              ? "this closes the mystery mix and completes the club. it can't be undone."
              : "this closes the mystery mix and opens the next one, starting its submission deadline. it can't be undone."}
          </p>
          <div className="flex items-center gap-4">
            <Button onPaper type="button" onClick={() => onAdvance(next)} disabled={advancing}>
              {advancing ? busyLabel : "yes, close mix"}
            </Button>
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={() => setConfirmingClose(false)}
              disabled={advancing}
            >
              cancel
            </Button>
          </div>
        </div>
      );
    }

    if (state === "open_voting" && confirmingRollback) {
      return (
        <div className="space-y-4">
          <p className="text-sm leading-[1.72] text-ink-muted">
            {totalVotes > 0
              ? `this reopens submissions with a fresh window and discards ${totalVotes} vote${totalVotes === 1 ? "" : "s"} already cast. it can't be undone.`
              : "this reopens submissions with a fresh window. it can't be undone."}
          </p>
          <div className="flex items-center gap-4">
            <Button onPaper type="button" onClick={onRollback} disabled={rollingBack}>
              {rollingBack ? "reopening…" : "yes, reopen submissions"}
            </Button>
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={() => setConfirmingRollback(false)}
              disabled={rollingBack}
            >
              cancel
            </Button>
          </div>
        </div>
      );
    }

    if (state === "open_voting" && extendingOpen) {
      return (
        <div className="space-y-4">
          <label htmlFor="extend-voting-deadline" className="block">
            <span className="block font-mono uppercase tracking-mono-caps text-mini text-ink-muted">
              new voting deadline (up to 48h later)
            </span>
            {/* Underline-only, matching TextField exactly: the resting underline
              is `muted-foreground` rather than `hairline` because here the
              underline IS the affordance and a ~1.2:1 edge fails WCAG 1.4.11.
              `focus:outline-none` is only acceptable because `focus:border-ink-accent`
              replaces the indicator it removes. Disabled drops the value to
              `muted-foreground` instead of fading the field (no opacity-50). */}
            <input
              id="extend-voting-deadline"
              type="datetime-local"
              value={chosenDeadline}
              min={minDatetime}
              max={maxDatetime}
              onChange={(e) => setChosenDeadline(e.target.value)}
              disabled={extendingVoting}
              className="mt-2 w-full rounded-none border-0 border-b border-ink-muted bg-transparent px-0 py-1 font-mono text-sm text-ink focus:border-ink-accent focus:outline-none disabled:cursor-not-allowed disabled:text-ink-muted"
            />
          </label>
          <div className="flex items-center gap-4">
            <Button
              onPaper
              type="button"
              onClick={handleSaveExtend}
              disabled={extendingVoting || !chosenDeadline}
            >
              {extendingVoting ? "saving…" : "save"}
            </Button>
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={() => setExtendingOpen(false)}
              disabled={extendingVoting}
            >
              cancel
            </Button>
          </div>
        </div>
      );
    }

    return (
      <>
        {/* All three are buttons at one weight. They are peers — each moves or
            corrects the mix's state — and none of them is the thing the
            organizer came to this screen for, so none gets the amber fill. The
            disclosure is what keeps the set from shouting at an organizer who
            is only reading; inside it, an amber row would just move the same
            noise one click deeper. */}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            onPaper
            variant="ghost"
            type="button"
            onClick={() => (next === "closed" ? setConfirmingClose(true) : onAdvance(next))}
            disabled={busy || blockedByMissingTheme}
          >
            {advancing ? busyLabel : label}
          </Button>
          {state === "open_voting" ? (
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={openExtendPicker}
              disabled={busy}
            >
              extend voting
            </Button>
          ) : null}
          {/* `reopen submissions` discards cast votes, so it keeps its own
              confirm step rather than relying on weight to slow anyone down. */}
          {state === "open_voting" ? (
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={() => setConfirmingRollback(true)}
              disabled={busy}
            >
              reopen submissions
            </Button>
          ) : null}
        </div>
        {blockedByMissingTheme ? (
          <p className="mt-3 text-sm leading-[1.72] text-ink-muted">
            set a theme below before opening this mystery mix.
          </p>
        ) : null}
      </>
    );
  }

  return (
    <div className="mt-6 border-t border-ink-hairline pt-6">
      {/* A heading wrapping a button: the standard disclosure shape, so the
          label stays in the screen's heading outline while still being the
          thing you click. `min-h-6` is the WCAG 2.5.8 target floor — this is a
          standalone control, not a link inside a sentence, so the inline
          exception doesn't cover it. */}
      <h2>
        <button
          type="button"
          onClick={toggleTools}
          aria-expanded={toolsOpen}
          aria-controls="admin-tools-panel"
          className="flex min-h-6 items-center gap-2 font-mono uppercase tracking-mono-wide text-meta text-ink-muted transition-colors duration-150 hover:text-ink"
        >
          <svg
            aria-hidden="true"
            width="8"
            height="8"
            viewBox="0 0 8 8"
            className={`shrink-0 transition-transform duration-150 ${toolsOpen ? "rotate-90" : ""}`}
          >
            <path d="M2 0.5 L6.5 4 L2 7.5 Z" fill="currentColor" />
          </svg>
          admin tools
        </button>
      </h2>
      {toolsOpen ? (
        <div id="admin-tools-panel" className="mt-4">
          {panel()}
        </div>
      ) : null}
    </div>
  );
}

/**
 * Organizer mix editor. Theme and description are the mix's identity — the
 * API allows editing them ONLY while the mix is `pending` (409 otherwise).
 * Once the mix opens there's nothing left to edit here, so the affordance
 * simply doesn't render for non-pending mixes.
 *
 * No accent of its own: the amber here belongs to the `Button` primitives and
 * the focused input underline, both of which are actions.
 */
function EditMixForm({
  mix,
  saving,
  error,
  onSave,
  onDismissError,
}: {
  mix: Mix;
  saving: boolean;
  error?: string | null;
  onSave: (input: {
    theme?: string | null;
    description?: string | null;
  }) => Promise<boolean | undefined>;
  onDismissError: () => void;
}) {
  // Themeless mixes can't open (MYS-211) — skip the "edit mix" click and show
  // the fields right away, since the organizer needs to fill this in before
  // they can do anything else with the mix.
  const [open, setOpen] = useState(!mix.theme);
  const [theme, setTheme] = useState(mix.theme ?? "");
  const [description, setDescription] = useState(mix.description ?? "");

  // Theme/description are only editable while the mix is still `pending`;
  // once it opens there's nothing left to edit, so don't render the affordance.
  if (mix.state !== "pending") return null;

  function openForm() {
    setTheme(mix.theme ?? "");
    setDescription(mix.description ?? "");
    onDismissError();
    setOpen(true);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const input: {
      theme?: string | null;
      description?: string | null;
    } = {};

    // Only send fields that changed. A cleared theme is sent as null so an
    // unnamed mix can be saved back to unnamed.
    const trimmedTheme = theme.trim();
    const currentTheme = mix.theme ?? "";
    if (trimmedTheme !== currentTheme) {
      input.theme = trimmedTheme ? trimmedTheme : null;
    }

    const trimmedDescription = description.trim();
    const currentDescription = mix.description ?? "";
    if (trimmedDescription !== currentDescription) {
      input.description = trimmedDescription ? trimmedDescription : null;
    }

    if (Object.keys(input).length === 0) {
      setOpen(false);
      return;
    }

    const ok = await onSave(input);
    if (ok) setOpen(false);
  }

  if (!open) {
    return (
      <div className="mt-4">
        <Button onPaper variant="ghost" type="button" onClick={openForm}>
          edit mix
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="mt-6 space-y-6 border-t border-ink-hairline pt-6"
    >
      <div>
        <TextField
          onPaper
          id="edit-mix-theme"
          label="theme"
          name="theme"
          value={theme}
          onChange={(e) => setTheme(e.target.value)}
          disabled={saving}
          autoComplete="off"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "edit-mix-error" : undefined}
        />
      </div>

      <label htmlFor="edit-mix-description" className="block">
        <span className="block font-mono uppercase tracking-mono-caps text-mini text-ink-muted">
          description
        </span>
        {/* Same underline treatment as TextField, including its resting
            `muted-foreground` rule — there is no textarea primitive. */}
        <textarea
          id="edit-mix-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={saving}
          className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink-muted bg-transparent px-0 py-1 font-mono text-sm text-ink placeholder:text-ink-muted focus:border-ink-accent focus:outline-none disabled:cursor-not-allowed disabled:text-ink-muted"
        />
      </label>

      {error ? (
        <FormError onPaper id="edit-mix-error">
          {error}
        </FormError>
      ) : null}

      <div className="flex items-center gap-4">
        <Button onPaper type="submit" disabled={saving}>
          {saving ? "saving…" : "save"}
        </Button>
        <Button
          onPaper
          variant="ghost"
          type="button"
          onClick={() => setOpen(false)}
          disabled={saving}
        >
          cancel
        </Button>
      </div>
    </form>
  );
}

/**
 * Submission progress (MYS-101): "X of Y submitted" while a mix is open for
 * submissions, so members can see how many picks are in. A quiet mono label,
 * never the accent — a progress readout is neither an action nor an
 * achievement. Renders nothing until the club's member count is known.
 */
function SubmissionProgress({ submitted, total }: { submitted: number; total: number }) {
  if (total <= 0) return null;
  return (
    <p
      role="status"
      aria-live="polite"
      className="mb-6 font-mono uppercase tracking-mono-caps text-mini text-ink-muted"
    >
      {submitted} of {total} submitted
    </p>
  );
}

/**
 * Album artwork at Z-Art — the one class of object that sits above the Z4
 * ceiling of the surface ladder, matching R11's `SongSearchCard` treatment. A
 * same-size `panel` block is laid down first and the image floats over it,
 * offset up and to the left, so the art reads as a physical object resting on
 * the card rather than as a picture printed into it. The block is what shows
 * while the image loads, and it is the entire treatment when `album_art_url`
 * is null (which it is for every legacy submission) — a null `src` would
 * render a broken image.
 *
 * The 1px white ring lives inside `shadow-z4` / `shadow-art`, so the art
 * carries no `border`. Art inside a hoverable row rests at `shadow-z4` and
 * rises to `shadow-art` on that row's hover; art in a non-interactive card
 * wears `shadow-art` at rest rather than advertising a hover that does
 * nothing.
 *
 * The offset only works if nothing clips it. No wrapper on any path to this
 * component sets `overflow-hidden` (`Card` does not, and neither do the vote
 * card, the tally rows, or any `<li>` here), and every offset stays inside its
 * container's own padding, so the art overlaps padding rather than escaping.
 *
 * Duplicated from `SongSearchCard`'s private `Thumb` rather than shared: that
 * one is not exported and this ticket's scope is these four files. The sweep
 * ticket can hoist a single `AlbumArt` primitive.
 */
function AlbumArt({
  url,
  alt,
  size,
  interactive = false,
}: {
  url: string | null;
  alt: string;
  size: number;
  /** Art inside a hoverable row: rest at `shadow-z4`, rise to `shadow-art`.
   *  Requires a `group` on the hover target. */
  interactive?: boolean;
}) {
  // Both inside the 4–12px the treatment calls for, and inside their
  // container's own padding.
  const offset = size >= 64 ? 6 : 4;
  return (
    <span className="relative block shrink-0" style={{ width: size, height: size }}>
      <span aria-hidden="true" className="block h-full w-full rounded-hair bg-panel" />
      {url ? (
        <img
          src={url}
          alt={alt}
          width={size}
          height={size}
          className={[
            "absolute rounded-hair object-cover transition-shadow duration-150",
            interactive ? "shadow-z4 group-hover:shadow-art" : "shadow-art",
          ].join(" ")}
          style={{ width: size, height: size, top: -offset, left: -offset }}
        />
      ) : null}
    </span>
  );
}

/** One of the player's submitted songs, with change/remove affordances. No
 *  accent beyond the `link`-style actions: a song you have already submitted
 *  is a completed fact, not an achievement, and at a club's song cap there can
 *  be several of these cards at once. */
function SubmittedSongCard({
  submission,
  eyebrow,
  busy,
  removing,
  onEdit,
  onRemove,
  onSaveNote,
}: {
  submission: SubmissionResult;
  eyebrow: ReactNode;
  busy: boolean;
  removing: boolean;
  onEdit: () => void;
  onRemove: () => void;
  onSaveNote: (note: string | null) => Promise<void>;
}) {
  const [editingNote, setEditingNote] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [savingNote, setSavingNote] = useState(false);

  function openNoteEditor() {
    setNoteText(submission.note ?? "");
    setEditingNote(true);
  }

  async function handleNoteSave() {
    setSavingNote(true);
    try {
      await onSaveNote(noteText.trim() || null);
      setEditingNote(false);
    } finally {
      setSavingNote(false);
    }
  }

  return (
    // A hover highlight, deliberately NOT the lift that club rows and mix rows
    // use. Those cards are buttons; this one is not — its actions are the
    // controls inside it — so `hover:shadow-z3` would advertise an affordance
    // that does not exist (see `Card`). One surface step to `popover` plus the
    // stronger hairline says "you are on this row" without claiming it is
    // clickable. Every text token still clears AA on `popover`: `foreground`
    // 16.64:1, `muted-foreground` 5.61:1, `subtle-foreground` 4.59:1.
    <Card className="transition-colors duration-150 hover:border-hairline-strong hover:bg-popover">
      <div className="flex items-start gap-4">
        <AlbumArt url={submission.album_art_url} alt={`${submission.title} album art`} size={56} />
        <div className="min-w-0 flex-1">
          <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            {eyebrow}
          </span>
          <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
            {submission.title}
          </h3>
          {submission.artist ? (
            <p className="mt-2 font-mono text-mini text-muted-foreground">{submission.artist}</p>
          ) : null}
        </div>
      </div>

      {editingNote ? (
        <div className="mt-3">
          <textarea
            maxLength={280}
            placeholder="add a note about this pick…"
            rows={2}
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            // Focus follows the user's own click on "add/edit note" (openNoteEditor,
            // above) — a disclosure pattern, not an unannounced page-load focus jump.
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            className="w-full resize-none rounded-none border-0 border-b border-muted-foreground bg-transparent px-0 py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:border-accent focus:outline-none"
          />
          <div className="mt-2 flex items-center gap-4">
            <button
              type="button"
              disabled={savingNote}
              onClick={() => void handleNoteSave()}
              className={ROW_ACTION_CLASS}
            >
              {savingNote ? "saving…" : "save note"}
            </button>
            <button
              type="button"
              disabled={savingNote}
              onClick={() => setEditingNote(false)}
              className={ROW_ACTION_MUTED_CLASS}
            >
              cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* The quote rule is a plain `hairline`: it appears on every card
              that carries a note, so an accent rule here would repeat down
              the list and read as the list's styling. */}
          {submission.note ? (
            <p className="mt-3 border-l-2 border-hairline pl-3 text-sm leading-[1.65] text-foreground">
              &ldquo;{submission.note}&rdquo;
            </p>
          ) : null}
          <div className="mt-3">
            <button
              type="button"
              disabled={busy}
              onClick={openNoteEditor}
              className={ROW_ACTION_MUTED_CLASS}
            >
              {submission.note ? "edit note" : "add a note"}
            </button>
          </div>
        </>
      )}

      <div className="mt-5 flex items-center gap-5">
        <button type="button" onClick={onEdit} disabled={busy} className={ROW_ACTION_CLASS}>
          change song
        </button>
        <button type="button" onClick={onRemove} disabled={busy} className={ROW_ACTION_MUTED_CLASS}>
          {removing ? "removing…" : "remove"}
        </button>
      </div>
    </Card>
  );
}

/** A submit/change composer in a slot — the search card plus an optional cancel
 *  (cancel only when editing an existing song, to drop back to its card). */
function ComposerSlot({
  heading,
  idPrefix,
  submitting,
  onSubmit,
  onCancel,
}: {
  heading: ReactNode;
  idPrefix: string;
  submitting: boolean;
  onSubmit: (song: ResolvedSong, note: string | null) => Promise<boolean> | void;
  onCancel?: () => void;
}) {
  const [noteText, setNoteText] = useState("");
  const { preferredService } = useAuth();
  return (
    <>
      <SongSearchCard
        eyebrow="this mix"
        heading={heading}
        helpAnchor="submitting-a-song"
        idPrefix={idPrefix}
        submitting={submitting}
        noteText={noteText}
        onNoteChange={setNoteText}
        preferredService={preferredService}
        onSubmit={async (song) => {
          const note = noteText.trim() || null;
          const ok = await Promise.resolve(onSubmit(song, note));
          if (ok !== false) setNoteText("");
          return ok ?? true;
        }}
      />
      {onCancel ? (
        <div className="mt-4">
          <Button onPaper variant="ghost" type="button" onClick={onCancel} disabled={submitting}>
            cancel
          </Button>
        </div>
      ) : null}
    </>
  );
}

/**
 * Multi-song submission manager (MYS-116/142). Shows one slot per song the
 * club allows (`cap`): a filled slot is a song card with change/remove, an
 * empty slot is a submit composer — so a 2-song club shows two submit cards up
 * front, no "add another" button. At cap 1 it's the classic single submit/edit.
 * The casual-mode stance is a club-level setting chosen by the organizer at
 * club creation; there is no per-player toggle here, so the stance is uniform
 * across all of a player's songs.
 *
 * No accent of its own — the amber here is the `Button` primitives (the
 * confirm CTA and the composer's submit) and hover states, all of which are
 * actions.
 */
function SubmissionManager({
  submissions,
  cap,
  submitting,
  removingId,
  onAdd,
  onEdit,
  onRemove,
  onSaveNote,
  onConfirm,
}: {
  submissions: SubmissionResult[];
  cap: number;
  submitting: boolean;
  removingId: string | null;
  onAdd: (song: ResolvedSong, note: string | null) => Promise<boolean>;
  onEdit: (submissionId: string, song: ResolvedSong, note: string | null) => Promise<boolean>;
  onRemove: (submissionId: string) => Promise<boolean>;
  onSaveNote: (submissionId: string, note: string | null) => Promise<void>;
  onConfirm: () => void;
}) {
  // Which already-submitted song is being changed (its slot shows a composer).
  const [editingId, setEditingId] = useState<string | null>(null);

  const busy = submitting || removingId !== null;
  // Show only the next empty slot — revealing all remaining slots simultaneously
  // lets users submit out of order, which confuses the positional slot labels.
  const emptySlots = submissions.length < cap ? 1 : 0;
  // Number the slots only when more than one is allowed, so a single-song
  // club reads exactly as before ("submit a song" / "your song").
  const numbered = cap > 1;
  // Once every slot is filled (multi-song only), offer a confirm that returns to
  // the club — the natural "I'm done submitting" exit.
  const allSubmitted = numbered && submissions.length === cap;

  return (
    <>
      {numbered && submissions.length > 0 ? (
        <h2 className="mb-4 font-mono uppercase tracking-mono-wide text-meta text-ink-muted">
          your songs · {submissions.length} of {cap}
        </h2>
      ) : null}

      <ul className="space-y-4">
        {submissions.map((s, i) =>
          editingId === s.id ? (
            <li key={s.id}>
              <ComposerSlot
                heading={
                  numbered ? (
                    <>
                      change song <span className="text-accent">{i + 1}</span>
                    </>
                  ) : (
                    "change your song"
                  )
                }
                idPrefix={`edit-${s.id}`}
                submitting={submitting}
                onSubmit={async (song, note) => {
                  const ok = await onEdit(s.id, song, note);
                  if (ok) setEditingId(null);
                  return ok;
                }}
                onCancel={() => setEditingId(null)}
              />
            </li>
          ) : (
            <li key={s.id}>
              <SubmittedSongCard
                submission={s}
                eyebrow={
                  numbered ? (
                    <>
                      song <span className="text-accent">{i + 1}</span>
                    </>
                  ) : (
                    "your song"
                  )
                }
                busy={busy}
                removing={removingId === s.id}
                onEdit={() => setEditingId(s.id)}
                onRemove={() => void onRemove(s.id)}
                onSaveNote={(note) => onSaveNote(s.id, note)}
              />
            </li>
          ),
        )}

        {/* One empty submit slot per remaining song the cap allows. Keyed by
            absolute slot position so a just-filled slot's composer unmounts
            cleanly instead of being reused (and carrying its resolved song). */}
        {Array.from({ length: emptySlots }, (_, i) => {
          const slot = submissions.length + i;
          return (
            <li key={`slot-${slot}`}>
              <ComposerSlot
                heading={
                  numbered ? (
                    <>
                      {/* The slot number in the accent, matching the mix number
                          on the page above. This card is `bg-card`, so `accent`
                          is 7.42:1 here — not the paper ramp. */}
                      submit song <span className="text-accent">{slot + 1}</span>
                    </>
                  ) : (
                    "submit a song"
                  )
                }
                idPrefix={`slot-${slot}`}
                submitting={submitting}
                onSubmit={onAdd}
              />
            </li>
          );
        })}
      </ul>

      {allSubmitted ? (
        <div className="mt-6 border-t border-hairline pt-6">
          <Button type="button" onClick={onConfirm} disabled={busy}>
            confirm
          </Button>
        </div>
      ) : null}
    </>
  );
}

// A source-only track (MYS-201) has a real track page on exactly one service
// family; every other platform's link is only a title/artist search that looks
// broken. Restrict the buttons to the platforms that are genuinely that track.
const SOURCE_PLATFORMS: Record<"youtube" | "bandcamp", PlatformKey[]> = {
  youtube: ["youtube", "youtubeMusic"],
  bandcamp: ["bandcamp"],
};

function PlatformLinks({
  platforms,
  title,
  source,
}: {
  platforms: Partial<Record<PlatformKey, string>>;
  title: string;
  source?: "youtube" | "bandcamp" | null;
}) {
  const available = PLATFORM_LABELS.filter((p) => {
    if (!platforms[p.key as PlatformKey]) return false;
    if (source) return SOURCE_PLATFORMS[source].includes(p.key as PlatformKey);
    return true;
  });
  if (available.length === 0) return null;
  return (
    // The ghost-button treatment as an anchor (matching R11's ResultView): a
    // `tile` fill rather than a bare hairline box, so each control is
    // identifiable without relying on a ~1.1:1 edge (WCAG 1.4.11). Neutral,
    // never amber — up to six of these render on every card in a list of
    // cards, which is the clearest case of amber-as-pattern on this screen.
    <ul className="mt-3 flex flex-wrap gap-2">
      {available.map((p) => (
        <li key={p.key}>
          <a
            href={platforms[p.key as PlatformKey]}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`open ${title} on ${p.label} (opens in a new tab)`}
            className="inline-flex items-center rounded-hair border border-hairline bg-tile px-3 py-2 font-mono uppercase tracking-mono text-label text-foreground transition-colors duration-150 hover:bg-panel"
          >
            {p.label}
          </a>
        </li>
      ))}
    </ul>
  );
}

/**
 * One-click "open the whole mix in YouTube" affordance (MYS-78). Renders only
 * when the backend resolved at least one track to YouTube (`youtubePlaylistUrl`
 * non-null). The subtle count line tells the listener how much of the mix made
 * it across.
 *
 * An amber `link`-variant anchor: opening the mix is an action, and there is
 * at most one of these per view. **No YouTube red.** Brand values live in
 * `lib/platformBrand.ts` and this affordance has never used one — the service
 * is named in the link text, and `SourceBadge` is the only place the app
 * spends a brand tint.
 */
function YouTubePlaylistRow({
  youtubePlaylistUrl,
  youtubeTrackCount,
  entryCount,
}: {
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
  entryCount: number;
}) {
  if (!youtubePlaylistUrl) return null;
  const complete = youtubeTrackCount >= entryCount;
  return (
    <PlaylistRow
      service="youtube"
      mark={<ServiceMark service="youtube" />}
      // Same phrasing as every other row, so completeness is comparable at a
      // glance rather than needing the numbers read.
      status={complete ? `all ${entryCount} songs` : `${youtubeTrackCount} of ${entryCount} songs`}
      action={
        <PlaylistLink href={youtubePlaylistUrl} label="open playlist in youtube">
          <MusicNoteIcon />
          open playlist
        </PlaylistLink>
      }
    />
  );
}

/**
 * Voting progress (MYS-102, terminology updated MYS-238): "X of Y competitive
 * mode voted or noted · Z casual mode". A quiet mono label so the room can see
 * how participation is filling in, never the accent — a progress readout is
 * neither an action nor an achievement. Renders nothing until there are
 * eligible (playing) voters.
 */
function VotingProgress({
  acted,
  eligible,
  vibing,
}: {
  acted: number;
  eligible: number;
  vibing: number;
}) {
  if (eligible <= 0) return null;
  return (
    <p className="mb-6 font-mono uppercase tracking-mono-caps text-mini text-ink-muted">
      {acted} of {eligible} competitive mode voted or noted
      {vibing > 0 ? ` · ${vibing} casual mode` : ""}
    </p>
  );
}

/** Pull the Bandcamp/YouTube-only picks out of a mix's tracklist for the unified
 *  source-only list, keyed off each track's own `source` (known at submission
 *  time, independent of whether any playlist has been generated). */
function toSourceOnly(
  items: {
    submission_id: string;
    title: string;
    artist: string;
    source: "youtube" | "bandcamp" | null;
    source_url: string | null;
  }[],
): MaybeMissingTrack[] {
  return items
    .filter((i) => i.source != null && i.source_url != null)
    .map((i) => ({
      submission_id: i.submission_id,
      title: i.title,
      artist: i.artist,
      source: i.source as "youtube" | "bandcamp",
      source_url: i.source_url as string,
    }));
}

/**
 * Listen affordance for a closed mix (MYS-133): the whole-mix YouTube +
 * Spotify links, so members can still play the mix after it closes. Reuses the
 * voting-screen components; renders nothing when the mix had no submissions.
 * The accent it carries belongs to the listen links themselves, which are
 * actions; the reveal's achievement amber is Most Noted and the Winner(s).
 */
function ClosedListen({
  mixId,
  youtubePlaylistUrl,
  youtubeTrackCount,
  entryCount,
  sourceOnly,
}: {
  mixId: string;
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
  entryCount: number;
  sourceOnly: MaybeMissingTrack[];
}) {
  if (entryCount === 0) return null;
  return (
    <div className="mb-10">
      <PlaylistsSection>
        <YouTubePlaylistRow
          youtubePlaylistUrl={youtubePlaylistUrl}
          youtubeTrackCount={youtubeTrackCount}
          entryCount={entryCount}
        />
        <SpotifyPlaylist mixId={mixId} entryCount={entryCount} />
        <AppleMusicPlaylist mixId={mixId} entryCount={entryCount} />
      </PlaylistsSection>
      <SongsMaybeMissing mixId={mixId} sourceOnly={sourceOnly} />
    </div>
  );
}

function VotingSection({
  mixId,
  entries,
  voteCounts,
  isVotesLocked,
  youtubePlaylistUrl,
  youtubeTrackCount,
  votingEligible,
  votingActed,
  vibingCount,
  votesPerPlayer,
  myVotes,
  isVibingParticipant,
  casting,
  votesSaved,
  onCast,
  onSelectionChange,
  onActionError,
}: {
  mixId: string;
  entries: PlaylistEntry[];
  voteCounts: VoteCountEntry[];
  isVotesLocked: boolean;
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
  votingEligible: number;
  votingActed: number;
  vibingCount: number;
  votesPerPlayer: number;
  myVotes: string[];
  isVibingParticipant: boolean;
  casting: boolean;
  votesSaved: boolean;
  onCast: (selected: string[]) => void;
  onSelectionChange: () => void;
  onActionError: (message: string | null) => void;
}) {
  // Seeded from the caller's saved votes; the parent remounts this component
  // (via key) whenever the saved set changes, re-seeding the selection.
  const [selected, setSelected] = useState<string[]>(myVotes);

  // If votes are locked, show the vote counts tally instead of voting controls
  if (isVotesLocked) {
    return (
      <VotingTally
        mixId={mixId}
        entries={entries}
        voteCounts={voteCounts}
        votesSaved={votesSaved}
        myVotes={myVotes}
        youtubePlaylistUrl={youtubePlaylistUrl}
        youtubeTrackCount={youtubeTrackCount}
      />
    );
  }

  if (entries.length === 0) {
    return <p className="text-sm leading-[1.72] text-muted-foreground">no submissions yet</p>;
  }

  function toggle(id: string) {
    onSelectionChange();
    setSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : current.length >= votesPerPlayer
          ? current
          : [...current, id],
    );
  }

  const atLimit = selected.length >= votesPerPlayer;

  // Vibing participants sit voting out — show the playlist, no controls.
  if (isVibingParticipant) {
    return (
      <>
        <VotingProgress acted={votingActed} eligible={votingEligible} vibing={vibingCount} />
        <p className="text-sm leading-[1.72] text-ink-muted">
          you&apos;re in casual mode for this one, so you sit voting out. settle in and enjoy the
          mix.
        </p>
        <PlaylistsSection>
          <YouTubePlaylistRow
            youtubePlaylistUrl={youtubePlaylistUrl}
            youtubeTrackCount={youtubeTrackCount}
            entryCount={entries.length}
          />
          <SpotifyPlaylist mixId={mixId} entryCount={entries.length} />
          <AppleMusicPlaylist mixId={mixId} entryCount={entries.length} />
        </PlaylistsSection>
        <SongsMaybeMissing mixId={mixId} sourceOnly={toSourceOnly(entries)} />
        <ul className="mt-4 space-y-4">
          {entries.map((entry) => (
            <li key={entry.submission_id}>
              {/* The SourceBadge below sits directly on `card` (4.74:1 for
                  YouTube, 5.98:1 for Bandcamp). Nothing lighter may go under
                  it — see the placement table in lib/platformBrand.ts. */}
              <Card>
                <div className="flex items-start gap-4">
                  <AlbumArt url={entry.album_art_url} alt={`${entry.title} album art`} size={56} />
                  <div className="min-w-0 flex-1">
                    <h3 className="font-display text-sm font-bold uppercase leading-none">
                      {entry.title}
                    </h3>
                    {entry.artist ? (
                      <p className="mt-2 font-mono text-mini text-muted-foreground">
                        {entry.artist}
                      </p>
                    ) : null}
                    {entry.source ? (
                      <div className="mt-2">
                        <SourceBadge source={entry.source} />
                      </div>
                    ) : null}
                  </div>
                </div>
                {entry.submitter_note ? (
                  <p className="mt-3 border-l-2 border-hairline pl-3 text-sm leading-[1.65] text-foreground">
                    &ldquo;{entry.submitter_note}&rdquo;
                  </p>
                ) : null}
                <PlatformLinks
                  platforms={entry.platforms}
                  title={entry.title}
                  source={entry.source}
                />
                {/* Vibers don't vote, but they can still leave notes — it's how
                    they take part (MYS-132). */}
                <SongNotes submissionId={entry.submission_id} onActionError={onActionError} />
              </Card>
            </li>
          ))}
        </ul>
      </>
    );
  }

  return (
    <>
      <VotingProgress acted={votingActed} eligible={votingEligible} vibing={vibingCount} />
      <PlaylistsSection>
        <YouTubePlaylistRow
          youtubePlaylistUrl={youtubePlaylistUrl}
          youtubeTrackCount={youtubeTrackCount}
          entryCount={entries.length}
        />
        <SpotifyPlaylist mixId={mixId} entryCount={entries.length} />
        <AppleMusicPlaylist mixId={mixId} entryCount={entries.length} />
      </PlaylistsSection>
      <SongsMaybeMissing mixId={mixId} sourceOnly={toSourceOnly(entries)} />
      <div className="flex items-baseline justify-between gap-4">
        <span className="flex items-baseline gap-2">
          <PaperSectionHeading>cast your votes</PaperSectionHeading>
          <HelpLink anchor="voting-results" onPaper />
        </span>
        <span
          aria-live="polite"
          className="font-mono uppercase tracking-mono-caps text-mini text-ink-muted"
        >
          {selected.length} / {votesPerPlayer} selected
        </span>
      </div>

      <ul className="mt-4 space-y-4">
        {entries.map((entry) => {
          // Your own song: shown in the playlist but never a vote toggle — you
          // can't vote for it (MYS-73), and it's clearly marked as yours
          // (MYS-74/75). No notes affordance either — you can't leave a note on
          // your own submission (MYS-77).
          //
          // No accent: "this one is mine" is a fact about the row, not an
          // action you can take on it or an achievement. The `your submission`
          // Badge and the explanatory line carry it, and the card drops to the
          // plain `card` surface every other row uses (the retired tinted fill
          // has no analogue here, and a lighter fill would also break the
          // SourceBadge placement constraint).
          if (entry.is_own) {
            return (
              <li key={entry.submission_id}>
                <Card>
                  <div className="flex items-start gap-4">
                    <AlbumArt
                      url={entry.album_art_url}
                      alt={`${entry.title} album art`}
                      size={56}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="font-display text-sm font-bold uppercase leading-none">
                          {entry.title}
                        </h3>
                        <span className="shrink-0">
                          <Badge>your submission</Badge>
                        </span>
                      </div>
                      {entry.artist ? (
                        <p className="mt-2 font-mono text-mini text-muted-foreground">
                          {entry.artist}
                        </p>
                      ) : null}
                      {entry.source ? (
                        <div className="mt-2">
                          <SourceBadge source={entry.source} />
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {entry.submitter_note ? (
                    <p className="mt-3 border-l-2 border-hairline pl-3 text-sm leading-[1.65] text-foreground">
                      &ldquo;{entry.submitter_note}&rdquo;
                    </p>
                  ) : null}
                  <p className="mt-2 font-mono text-mini text-muted-foreground">
                    you can&apos;t vote for your own song
                  </p>
                  <PlatformLinks
                    platforms={entry.platforms}
                    title={entry.title}
                    source={entry.source}
                  />
                </Card>
              </li>
            );
          }
          const isSelected = selected.includes(entry.submission_id);
          const disabled = !isSelected && atLimit;
          return (
            <li key={entry.submission_id}>
              {/* Card wrapper — owns the surface/border/radius so notes can live
                  inside without nesting interactive elements inside the vote
                  button. Hand-built rather than the `Card` primitive because
                  the border is stateful and the button has to reach the card's
                  own edges.

                  **Amber marks the selected row, and this is the one place on
                  this screen where a per-row accent survives.** It is an
                  interactive state (amber's action half), it is entirely
                  user-driven rather than a property of the data, it is bounded
                  by `votes_per_player`, and the design system's own AlbumCard
                  marks exactly this "I picked this one" state in amber. The
                  `voted` label carries the state too, so the border is never
                  the sole identifier (WCAG 1.4.11).

                  A row you can no longer select (at the vote limit) drops its
                  title to `muted-foreground` rather than taking `opacity-50` —
                  on a near-black page opacity flattens a card into the
                  background instead of quieting it. */}
              <div
                className={[
                  "rounded-tile border bg-card shadow-z2 transition-colors duration-150",
                  isSelected ? "border-accent" : "border-hairline",
                ].join(" ")}
              >
                {/* Vote toggle — only the top portion of the card is clickable.
                    Hover lifts to `popover`, the lightest surface a brand-tinted
                    SourceBadge may sit on (4.40:1 for YouTube); `tile` and above
                    would fail AA. See lib/platformBrand.ts. */}
                <button
                  type="button"
                  aria-pressed={isSelected}
                  disabled={disabled}
                  onClick={() => toggle(entry.submission_id)}
                  className={[
                    "group block w-full rounded-t-tile px-6 pt-5 pb-3 text-left",
                    disabled ? "cursor-not-allowed" : "cursor-pointer",
                    !isSelected && !disabled ? "hover:bg-popover" : "",
                  ].join(" ")}
                >
                  <div className="flex items-start gap-4">
                    <AlbumArt
                      url={entry.album_art_url}
                      alt={`${entry.title} album art`}
                      size={56}
                      interactive
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <h3
                          className={[
                            "font-display text-sm font-bold uppercase leading-none",
                            disabled ? "text-muted-foreground" : "text-foreground",
                          ].join(" ")}
                        >
                          {entry.title}
                        </h3>
                        {/* The vote control. An UNSELECTED card previously showed
                            nothing here, so its only interactive cue was a
                            `hairline` border at ~1.2:1 plus a hover state — and
                            hover does not exist on touch. That left the one card
                            you cannot vote for ("your submission") as the most
                            marked row in the list.

                            The empty ring is what says "this is a control". It
                            is `muted-foreground` at 6.01:1 on `card`, well clear
                            of the 3:1 a non-text graphic owes. Selected fills it
                            amber and adds the word, so state is never colour
                            alone (WCAG 1.4.11). At the vote limit the ring drops
                            to `ghost-foreground`, the ramp's disabled-glyph step
                            — WCAG exempts inactive controls, and it reads as
                            unavailable rather than merely dim.

                            NOTE (MysteryMixClub-ih3l): this is a binary marker
                            because a player may currently vote for a song at
                            most once. When weighted voting lands it becomes a
                            quantity, so expect to replace this rather than
                            extend it. */}
                        <span className="flex shrink-0 items-center gap-2">
                          <span className="font-mono uppercase tracking-mono-caps text-mini text-accent">
                            {isSelected ? "voted" : ""}
                          </span>
                          <span
                            aria-hidden="true"
                            className={[
                              "block h-4 w-4 rounded-full border transition-colors duration-150",
                              isSelected
                                ? "border-accent bg-accent"
                                : disabled
                                  ? "border-ghost-foreground"
                                  : "border-muted-foreground group-hover:border-foreground",
                            ].join(" ")}
                          />
                        </span>
                      </div>
                      {entry.artist ? (
                        <p className="mt-2 font-mono text-mini text-muted-foreground transition-colors duration-150 group-hover:text-foreground">
                          {entry.artist}
                        </p>
                      ) : null}
                      {entry.source ? (
                        <div className="mt-2">
                          <SourceBadge source={entry.source} />
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {entry.submitter_note ? (
                    <p className="mt-3 border-l-2 border-hairline pl-3 text-sm leading-[1.65] text-foreground">
                      &ldquo;{entry.submitter_note}&rdquo;
                    </p>
                  ) : null}
                </button>
                {/* Platform links + notes live inside the card, below the vote area. */}
                <div className="px-6 pb-5">
                  <PlatformLinks
                    platforms={entry.platforms}
                    title={entry.title}
                    source={entry.source}
                  />
                  <SongNotes submissionId={entry.submission_id} onActionError={onActionError} />
                </div>
              </div>
            </li>
          );
        })}
      </ul>

      <div className="mt-6 border-t border-ink-hairline pt-6">
        <Button
          type="button"
          onPaper
          onClick={() => onCast(selected)}
          disabled={casting || selected.length === 0}
        >
          {casting ? "casting…" : "cast votes"}
        </Button>
        {/* `foreground`, not the accent: "your votes saved" is a completed
            fact, not an action or an achievement — the same reasoning R10 used
            for its viewer-participation checks. */}
        {votesSaved ? (
          <p
            aria-live="polite"
            className="mt-3 font-mono uppercase tracking-mono-caps text-mini text-foreground"
          >
            votes saved
          </p>
        ) : null}
      </div>
    </>
  );
}

/**
 * Vote tally (MYS-148): shows running vote counts per song once voting is locked.
 * This replaces the voting controls after a player has cast their votes.
 * The vote counts update automatically as others vote, but notes remain hidden
 * until the mix closes (MYS-72 - notes revealed only in the reveal).
 *
 * Keeps the playlist links visible (MYS-236) — locking in a vote shouldn't cut
 * a player off from actually listening to the mix.
 *
 * **No accent anywhere in the tally.** A locked tally is informational: the
 * caller can no longer act on it, and a running vote count is nobody's
 * achievement until the mix closes. It is also one row per song, unbounded, so
 * even an in-category marker would repeat down the list and read as the list's
 * styling. The row the caller voted for is told apart structurally instead —
 * a `hairline-strong` edge (the step meant for an element that has to read
 * against its neighbours), a `foreground` label, and the checkmark glyph, so
 * the distinction survives without color at all.
 */
function VotingTally({
  mixId,
  entries,
  voteCounts,
  votesSaved,
  myVotes,
  youtubePlaylistUrl,
  youtubeTrackCount,
}: {
  mixId: string;
  entries: PlaylistEntry[];
  voteCounts: VoteCountEntry[];
  votesSaved: boolean;
  myVotes: string[];
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
}) {
  // Sort by vote count desc, then title asc for deterministic order
  const sorted = [...voteCounts].sort((a, b) => {
    if (b.vote_count !== a.vote_count) {
      return b.vote_count - a.vote_count;
    }
    return a.title.localeCompare(b.title);
  });

  // Which songs the caller actually voted for (MYS-171) — a submission_id
  // membership check, not a rank cutoff, so it stays correct regardless of how
  // the tally sorts (a song you voted for that isn't currently leading still
  // gets marked).
  const votedIds = new Set(myVotes);
  const totalVotes = voteCounts.reduce((sum, entry) => sum + entry.vote_count, 0);

  return (
    <>
      <p className="text-sm leading-[1.72] text-muted-foreground">
        you&apos;ve locked in your votes — check back to see how the voting goes.
      </p>
      <PlaylistsSection>
        <YouTubePlaylistRow
          youtubePlaylistUrl={youtubePlaylistUrl}
          youtubeTrackCount={youtubeTrackCount}
          entryCount={entries.length}
        />
        <SpotifyPlaylist mixId={mixId} entryCount={entries.length} />
        <AppleMusicPlaylist mixId={mixId} entryCount={entries.length} />
      </PlaylistsSection>
      <SongsMaybeMissing mixId={mixId} sourceOnly={toSourceOnly(entries)} />
      <PaperSectionHeading className="mt-8">
        vote tally ({voteCounts.length} songs)
      </PaperSectionHeading>
      <p role="status" aria-live="polite" className="sr-only">
        {totalVotes} votes counted so far
      </p>
      <div className="mt-4 space-y-3">
        {sorted.map((entry, i) => {
          const isVoted = votedIds.has(entry.submission_id);
          return (
            <div
              key={entry.submission_id}
              className={[
                "flex items-center justify-between rounded-hair border bg-card px-4 py-3",
                isVoted ? "border-hairline-strong" : "border-hairline-soft",
              ].join(" ")}
            >
              <div className="flex items-center gap-3 overflow-hidden">
                <span className="w-6 shrink-0 font-mono text-mini text-muted-foreground">
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p
                    className="truncate font-display text-sm font-semibold uppercase leading-none"
                    title={entry.title}
                  >
                    {entry.title}
                  </p>
                  <p className="mt-1.5 truncate font-mono text-mini text-muted-foreground">
                    {entry.artist}
                  </p>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <span className="block font-mono text-sm text-foreground">
                  {entry.vote_count} {entry.vote_count === 1 ? "vote" : "votes"}
                </span>
                {isVoted && (
                  <span className="inline-flex items-center gap-1 font-mono uppercase tracking-mono text-mini text-foreground">
                    <CheckmarkIcon />
                    your vote
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {myVotes.length > 0 && (
        <div className="mt-6 border-t border-hairline pt-6">
          <p className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            your votes are locked — they will be revealed when the mystery mix closes
          </p>
        </div>
      )}
      {/* Show "votes saved" confirmation even when locked (after casting) */}
      {votesSaved && (
        <p
          aria-live="polite"
          className="mt-6 font-mono uppercase tracking-mono-caps text-mini text-foreground"
        >
          votes saved
        </p>
      )}
    </>
  );
}

const NOTE_MAX = 280;

/**
 * Per-song notes affordance for the open_voting playlist. Lazily loads the
 * notes for a submission when first revealed, lists them, and offers an
 * expandable inline composer (underline-style textarea + live N/280 counter).
 * Eligible on every song; the vibing placement passes the calmer composerHint.
 * Errors are surfaced through the page-level actionError region.
 */
function SongNotes({
  submissionId,
  onActionError,
  composerHint,
}: {
  submissionId: string;
  onActionError: (message: string | null) => void;
  composerHint?: string;
}) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);

  const reveal = useCallback(async () => {
    const next = !open;
    setOpen(next);
    if (next && !loaded) {
      try {
        setNotes(await getNotes(submissionId));
        setLoaded(true);
      } catch (err) {
        onActionError(err instanceof ApiError ? err.message : "couldn't load notes.");
      }
    }
  }, [open, loaded, submissionId, onActionError]);

  // MYS-257: one note per player per song. While voting is open, GET only
  // ever returns the caller's own notes, so a non-empty loaded list here
  // means they already have theirs — open the composer pre-filled with it
  // (edit) instead of a blank one (leave). If we haven't loaded yet, load
  // first to find out; this also covers a second tab / stale-state 409/404
  // as a fallback.
  async function startComposing() {
    if (!loaded) {
      try {
        const fetched = await getNotes(submissionId);
        setNotes(fetched);
        setLoaded(true);
        if (fetched.length > 0) {
          setDraft(fetched[0].body);
        }
      } catch (err) {
        onActionError(err instanceof ApiError ? err.message : "couldn't load notes.");
        return;
      }
    } else if (notes.length > 0) {
      setDraft(notes[0].body);
    }
    setComposing(true);
    setOpen(true);
  }

  const ownNote = loaded && notes.length > 0 ? notes[0] : null;

  async function submit() {
    const body = draft.trim();
    if (!body || body.length > NOTE_MAX || posting) return;
    setPosting(true);
    onActionError(null);
    try {
      if (ownNote) {
        const updated = await editNote(submissionId, body);
        setNotes((current) => current.map((n) => (n.id === updated.id ? updated : n)));
      } else {
        const created = await addNote(submissionId, body);
        setNotes((current) => [...current, created]);
        setLoaded(true);
      }
      setDraft("");
      setComposing(false);
      setOpen(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 409 || err.status === 404)) {
        // Out of sync with the server (race with another tab/session, or the
        // note we thought we had is gone) — refresh so the UI reflects
        // reality instead of leaving a dead composer open.
        setComposing(false);
        try {
          setNotes(await getNotes(submissionId));
          setLoaded(true);
        } catch {
          // best-effort refresh; the error message below still surfaces.
        }
      }
      onActionError(
        err instanceof ApiError
          ? err.message
          : `couldn't ${ownNote ? "save your edit" : "leave your note"}. try again.`,
      );
    } finally {
      setPosting(false);
    }
  }

  const count = draft.trim().length;
  const submitDisabled = posting || count === 0 || count > NOTE_MAX;

  return (
    <div className="mt-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <button
          type="button"
          onClick={() => void reveal()}
          aria-expanded={open}
          className={ROW_ACTION_MUTED_CLASS}
        >
          notes{loaded ? ` (${notes.length})` : ""}
        </button>
        {!composing ? (
          <button type="button" onClick={() => void startComposing()} className={ROW_ACTION_CLASS}>
            {ownNote ? "edit note" : "leave a note"}
          </button>
        ) : null}
      </div>

      {open ? (
        <>
          {composing ? (
            <div className="mt-4">
              {composerHint ? (
                <p className="text-meta leading-[1.6] text-muted-foreground">{composerHint}</p>
              ) : null}
              <label className="mt-2 block">
                <span className="block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  your note
                </span>
                <textarea
                  value={draft}
                  maxLength={NOTE_MAX}
                  rows={2}
                  onChange={(e) => setDraft(e.target.value)}
                  className="mt-2 w-full resize-none rounded-none border-0 border-b border-muted-foreground bg-transparent px-0 py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:border-accent focus:outline-none"
                />
              </label>
              <div className="mt-2 flex items-center justify-between gap-4">
                <span
                  aria-live="polite"
                  className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground"
                >
                  {count} / {NOTE_MAX}
                </span>
                <div className="flex items-center gap-4">
                  <button
                    type="button"
                    onClick={() => {
                      setComposing(false);
                      setDraft("");
                    }}
                    className={ROW_ACTION_MUTED_CLASS}
                  >
                    cancel
                  </button>
                  <Button type="button" onClick={() => void submit()} disabled={submitDisabled}>
                    {posting ? "saving…" : ownNote ? "save note" : "leave note"}
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {loaded && notes.length > 0 && !composing ? (
            <ul className="mt-4 space-y-3 border-t border-hairline-soft pt-4">
              {notes.map((note) => (
                <li key={note.id}>
                  <p className="text-sm leading-[1.65] text-foreground">{note.body}</p>
                  <span className="mt-1 block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                    {note.author_display_name}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {loaded && notes.length === 0 && !composing ? (
            <p className="mt-3 text-meta leading-[1.6] text-muted-foreground">no notes yet</p>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

/** A list of reveal notes (body + author), shared by Most Noted and each
 *  submission card. Calm, read-only — no composer in the closed view. */
function ResultNoteList({ notes }: { notes: ResultNote[] }) {
  return (
    <ul className="space-y-3">
      {notes.map((note, i) => (
        <li key={i}>
          <p className="text-sm leading-[1.65] text-foreground">{note.body}</p>
          <span className="mt-1 block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            {note.author_display_name}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** A player's songs gathered into one standing for the reveal (MYS-116/143):
 *  their per-song tiles plus the per-player vote total the leaderboard ranks on. */
type PlayerGroup = {
  userId: string;
  displayName: string;
  total: number;
  songs: ResultSubmission[];
};

/** Group a mix's submissions by submitter, summing votes across each player's
 *  songs — so a multi-song player reads as a single entrant (MYS-116). Order
 *  follows the incoming (vote-sorted) submissions: a player first appears where
 *  their best song does. */
function groupByPlayer(submissions: ResultSubmission[]): PlayerGroup[] {
  const groups = new Map<string, PlayerGroup>();
  for (const s of submissions) {
    const existing = groups.get(s.user_id);
    if (existing) {
      existing.total += s.vote_count;
      existing.songs.push(s);
    } else {
      groups.set(s.user_id, {
        userId: s.user_id,
        displayName: s.submitter_display_name,
        total: s.vote_count,
        songs: [s],
      });
    }
  }
  return [...groups.values()];
}

/**
 * The winning player(s) of the mix — the most votes by per-player total, so
 * the highlight matches the leaderboard (MYS-116). A tie shows every winner.
 * Returns [] when nobody drew a vote. Every submitter competes, vibers included
 * (MYS-112).
 */
function topPlayers(groups: PlayerGroup[]): PlayerGroup[] {
  const top = groups.reduce((max, g) => Math.max(max, g.total), 0);
  if (top <= 0) return [];
  return groups.filter((g) => g.total === top);
}

/**
 * A submission's notes on the reveal, collapsed by default behind a "N notes"
 * toggle so a long thread doesn't bury the picks list (MYS-72). Used on the
 * picks cards; Most Noted keeps its notes open, since seeing them is the point.
 */
function CollapsibleNotes({ notes }: { notes: ResultNote[] }) {
  const [open, setOpen] = useState(false);
  const label = `${notes.length} ${notes.length === 1 ? "note" : "notes"}`;
  return (
    <div className="mt-4 border-t border-hairline-soft pt-4">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={ROW_ACTION_MUTED_CLASS}
      >
        {open ? `hide ${label}` : `show ${label}`}
      </button>
      {open ? (
        <div className="mt-4">
          <ResultNoteList notes={notes} />
        </div>
      ) : null}
    </div>
  );
}

/**
 * Closed-mix reveal (MYS-24 / MYS-71). A static results moment — subtle
 * fade-in only, no staged animation (deferred to MYS-54). Top to bottom: Most
 * Noted, the Winner(s) by votes, the Playing leaderboard, then a single ranked
 * "the picks" list with every submission's full detail (submitter, notes,
 * platforms, voters) — the standalone compact song-rank list was folded into
 * this one to avoid listing every song twice (MYS-173 follow-up).
 *
 * **Where the reveal's achievement amber goes.** Most Noted and the Winner(s):
 * exactly one section of each per mix, and each is a genuine achievement, so
 * both keep it (the crown glyph, and Most Noted's accent bar). The picks list
 * does NOT — see `RankBadge`.
 */
function ResultsSection({
  results,
  userId,
  onActionError,
}: {
  results: MixResults | null;
  userId: string | null;
  onActionError: (message: string | null) => void;
}) {
  if (!results) {
    return <p className="text-sm leading-[1.72] text-muted-foreground">no submissions</p>;
  }

  // A vibing viewer gets the trimmed reveal — winner(s) + Most Noted + their own
  // song's notes, no rankings or vote counts (MYS-112).
  if (results.viewer_is_vibing) {
    return <VibingReveal results={results} onActionError={onActionError} />;
  }

  if (results.submissions.length === 0) {
    return <p className="text-sm leading-[1.72] text-muted-foreground">no submissions</p>;
  }

  const { submissions, leaderboard, most_noted } = results;
  const nameFor = (uid: string, displayName: string | null) =>
    uid === userId ? "you" : (displayName ?? "someone");
  const winners = topPlayers(groupByPlayer(submissions));

  return (
    <div className="animate-fade-in space-y-12">
      {most_noted.winners.length > 0 ? <MostNotedSection winners={most_noted.winners} /> : null}

      {winners.length > 0 ? <WinnersSection winners={winners} nameFor={nameFor} /> : null}

      {leaderboard.length > 0 ? <LeaderboardSection entries={leaderboard} /> : null}

      {submissions.length > 0 ? (
        <section>
          <PaperSectionHeading>the picks ({submissions.length})</PaperSectionHeading>
          <ul className="mt-4 space-y-4">
            {rankSongs(submissions).map((s) => (
              <li key={s.submission_id}>
                <Card>
                  <div className="flex items-start gap-4">
                    <RankBadge rank={s.rank} />
                    {/* 40px, not the 56px the standalone song cards use: this
                        row already spends a rail on the rank badge, and the
                        picks list is the densest one on the screen. */}
                    <AlbumArt url={s.album_art_url} alt={`${s.title} album art`} size={40} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                          {nameFor(s.user_id, s.submitter_display_name)}
                        </span>
                        <span className="flex shrink-0 flex-col items-end">
                          <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                            {s.vote_count} {s.vote_count === 1 ? "vote" : "votes"}
                          </span>
                          {s.tied ? (
                            <span className="mt-0.5 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                              tied
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
                        {s.title}
                      </h3>
                      {s.artist ? (
                        <p className="mt-2 font-mono text-mini text-muted-foreground">{s.artist}</p>
                      ) : null}
                      {s.source ? (
                        <div className="mt-2">
                          <SourceBadge source={s.source} />
                        </div>
                      ) : null}
                      {s.submitter_note ? (
                        <p className="mt-2 text-meta leading-[1.6] text-foreground">
                          “{s.submitter_note}”
                        </p>
                      ) : null}
                      <PlatformLinks platforms={s.platforms} title={s.title} source={s.source} />
                      {s.voters.length > 0 ? (
                        <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
                          voted by {s.voters.map((v) => v.display_name).join(", ")}
                        </p>
                      ) : null}
                      {s.notes.length > 0 ? <CollapsibleNotes notes={s.notes} /> : null}
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/**
 * A song's rank within its mix. Top 3 get a medal glyph so they read as
 * distinct at a glance; rank 4 and below is a plain numeral.
 *
 * **The medals are neutral, and this is a deliberate drop.** Amber's category
 * does cover achievement, and the style guide names "rank-1 indicators" among
 * its uses — but this is a per-row marker on the full ranked tracklist, which
 * runs one row per submission with no cap, and three of every list would carry
 * it. That is amber as pattern, which the category rule forbids however
 * in-category the rank-1 row alone would be. It would also be the *second*
 * amber statement of the same fact: the Winner(s) section directly above
 * already marks who won, and it is bounded to one section per mix. Same
 * conclusion R8 reached about completed club cards and R10 about per-mix
 * winner lines. Weight carries the ranking instead — a larger `foreground`
 * medal for 1st, `muted-foreground` for 2nd/3rd.
 */
function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center font-mono text-mini text-muted-foreground">
        {rank}
      </span>
    );
  }
  // 1st place reads slightly larger and brighter than 2nd/3rd. The numeral
  // sits inside the medal's disc — centered on its (6, 4.5) midpoint in the
  // icon's 0-12 viewBox, i.e. 50% across / 37.5% down the rendered icon.
  const first = rank === 1;
  return (
    <span
      className={[
        "relative shrink-0",
        first ? "h-7 w-7 text-foreground" : "h-6 w-6 text-muted-foreground",
      ].join(" ")}
    >
      <MedalIcon className="h-full w-full" />
      {/* The numeral is real text (not decorative like the medal outline
          above), so it carries `foreground` in both cases rather than
          inheriting the 2nd/3rd medal's dimmer stroke color. */}
      <span
        className={[
          "absolute left-1/2 top-[37.5%] -translate-x-1/2 -translate-y-1/2 font-mono leading-none text-foreground",
          first ? "text-label" : "text-mini",
        ].join(" ")}
      >
        {rank}
      </span>
    </span>
  );
}

/**
 * The reveal a vibing viewer sees (MYS-112 / MYS-134): Most Noted, the
 * winner(s) by votes — named, no counts — and the full tracklist with notes
 * but NO scores or leaderboard. Same amber budget as the full reveal: the two
 * achievement sections, and nothing per-row.
 */
function VibingReveal({
  results,
  onActionError,
}: {
  results: MixResults;
  onActionError: (message: string | null) => void;
}) {
  const { most_noted, winners, picks } = results;
  return (
    <div className="animate-fade-in space-y-12">
      {most_noted.winners.length > 0 ? <MostNotedSection winners={most_noted.winners} /> : null}

      {winners.length > 0 ? <VibeWinnersSection winners={winners} /> : null}

      {picks.length > 0 ? <VibePicksSection picks={picks} onActionError={onActionError} /> : null}
    </div>
  );
}

/** The winner(s) as shown to a vibing viewer — named, no vote counts. */
function VibeWinnersSection({ winners }: { winners: WinnerReveal[] }) {
  const tie = winners.length > 1;
  return (
    <section>
      {/* The crown is amber: winning a mix is an achievement, and there is
          exactly one winner section per reveal. */}
      <PaperSectionHeading className="inline-flex items-center gap-2">
        <CrownIcon className="text-ink-accent" />
        {tie ? "winners" : "winner"}
      </PaperSectionHeading>
      <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
        {tie ? "the most-loved picks this mystery mix" : "the most-loved pick this mystery mix"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.submission_id}>
            <Card>
              <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                {w.submitter_display_name ?? "someone"}
              </span>
              <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
                {w.title}
              </h3>
              {w.artist ? (
                <p className="mt-2 font-mono text-mini text-muted-foreground">{w.artist}</p>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The full tracklist as a vibing viewer sees it (MYS-134): every submitted song
 *  with its submitter and notes, but NO vote counts or ranking — so they can see
 *  what was in the mix without any scores. A vibing viewer may keep leaving or
 *  editing their own note on any pick even after the reveal (MYS-256
 *  follow-up), so this renders the live SongNotes composer+list rather than
 *  the read-only CollapsibleNotes used elsewhere on the reveal. */
function VibePicksSection({
  picks,
  onActionError,
}: {
  picks: RevealPick[];
  onActionError: (message: string | null) => void;
}) {
  return (
    <section>
      <PaperSectionHeading>the picks ({picks.length})</PaperSectionHeading>
      <ul className="mt-4 space-y-4">
        {picks.map((p) => (
          // `RevealPick` carries no `album_art_url` (the vibe-safe shape is
          // deliberately narrower than `ResultSubmission`), so there is no
          // artwork to render here.
          <li key={p.submission_id}>
            <Card>
              <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                {p.submitter_display_name ?? "someone"}
              </span>
              <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
                {p.title}
              </h3>
              {p.artist ? (
                <p className="mt-2 font-mono text-mini text-muted-foreground">{p.artist}</p>
              ) : null}
              {p.source ? (
                <div className="mt-2">
                  <SourceBadge source={p.source} />
                </div>
              ) : null}
              {p.submitter_note ? (
                <p className="mt-2 text-meta leading-[1.6] text-foreground">“{p.submitter_note}”</p>
              ) : null}
              <PlatformLinks platforms={p.platforms} title={p.title} source={p.source} />
              <SongNotes submissionId={p.submission_id} onActionError={onActionError} />
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The single most important element on the reveal — the song(s) that drew the
 * most notes. A tie shows every winner as co-recognized.
 *
 * This is the reveal's strongest achievement statement and it keeps the accent
 * on both counts: an amber crown in the heading and the `Card`'s amber left
 * bar. There is exactly one most-noted section per mix, so neither repeats —
 * a tie co-recognizes at most a handful of picks and is the rare case, not the
 * shape of the list.
 */
function MostNotedSection({ winners }: { winners: MostNotedWinner[] }) {
  const tie = winners.length > 1;
  return (
    <section>
      <PaperSectionHeading className="inline-flex items-center gap-2">
        <CrownIcon className="text-ink-accent" />
        most noted
      </PaperSectionHeading>
      <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
        {tie ? "the picks that got everyone talking" : "the pick that got everyone talking"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.submission_id}>
            {/* `MostNotedWinner` carries no `album_art_url`, so no artwork. */}
            <Card bar="accent">
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-display text-sm font-bold uppercase leading-none">{w.title}</h3>
                <span className="shrink-0 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  {w.note_count} {w.note_count === 1 ? "note" : "notes"}
                </span>
              </div>
              {w.artist ? (
                <p className="mt-2 font-mono text-mini text-muted-foreground">{w.artist}</p>
              ) : null}
              {w.notes.length > 0 ? (
                <div className="mt-5 border-t border-hairline-soft pt-5">
                  <ResultNoteList notes={w.notes} />
                </div>
              ) : null}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The mix's winner(s) by votes — prominent but secondary to Most Noted. A tie
 * co-recognizes every top-voted pick.
 *
 * Winning is an achievement and there is one winner section per mix, so the
 * heading crown is amber. The card itself stays plain rather than taking
 * `Card accent` too: Most Noted keeps the accent *bar* so the two achievement
 * sections still read in order rather than as one undifferentiated block.
 */
function WinnersSection({
  winners,
  nameFor,
}: {
  winners: PlayerGroup[];
  nameFor: (userId: string, displayName: string | null) => string;
}) {
  const tie = winners.length > 1;
  return (
    <section>
      <PaperSectionHeading className="inline-flex items-center gap-2">
        <CrownIcon className="text-ink-accent" />
        {tie ? "winners" : "winner"}
      </PaperSectionHeading>
      <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
        {tie ? "tied for the most votes this mystery mix" : "the most votes this mystery mix"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.userId}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  {nameFor(w.userId, w.displayName)}
                </span>
                {/* The per-player total — the score the leaderboard ranks on. */}
                <span className="shrink-0 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  {w.total} {w.total === 1 ? "vote" : "votes"}
                </span>
              </div>
              {/* Show only the player's top-voted song(s), not every submission
                  (MYS-150). A multi-song winner lists their peak songs under one
                  total; ties at the peak show each. */}
              {(() => {
                const peak = Math.max(...w.songs.map((s) => s.vote_count));
                return w.songs
                  .filter((s) => s.vote_count === peak)
                  .map((s, i) => (
                    <div
                      key={s.submission_id}
                      className={["flex items-start gap-4", i === 0 ? "mt-2" : "mt-4"].join(" ")}
                    >
                      <AlbumArt url={s.album_art_url} alt={`${s.title} album art`} size={56} />
                      <div className="min-w-0 flex-1">
                        <h3 className="font-display text-sm font-bold uppercase leading-none">
                          {s.title}
                        </h3>
                        {s.artist ? (
                          <p className="mt-2 font-mono text-mini text-muted-foreground">
                            {s.artist}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  ));
              })()}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Attach a competition rank to each song: ties share the same rank number and
 *  the next distinct score gets the position it would occupy if the tied entries
 *  were counted separately (1, 1, 3 — not 1, 1, 2). `tied` flags any song that
 *  shares its rank with another, so the card can call it out explicitly. */
function rankSongs(
  submissions: ResultSubmission[],
): Array<ResultSubmission & { rank: number; tied: boolean }> {
  const sorted = [...submissions].sort((a, b) => b.vote_count - a.vote_count);
  let rank = 1;
  const ranked = sorted.map((s, i) => {
    if (i > 0 && sorted[i - 1].vote_count > s.vote_count) rank = i + 1;
    return { ...s, rank };
  });
  const countByRank = new Map<number, number>();
  for (const s of ranked) countByRank.set(s.rank, (countByRank.get(s.rank) ?? 0) + 1);
  return ranked.map((s) => ({ ...s, tied: (countByRank.get(s.rank) ?? 0) > 1 }));
}

/**
 * The Playing leaderboard — already ranked, vibing excluded. Calm and compact.
 *
 * **No accent, not even on rank 1.** Unlike `ClubHomeScreen`'s all-time
 * standings — the one table on that screen, where rank 1 legitimately takes
 * the amber row — this leaderboard sits directly beneath a Winner(s) section
 * that already marks the same player as the achievement. Marking them twice
 * on one screen makes the accent read as decoration on the second pass.
 */
function LeaderboardSection({ entries }: { entries: LeaderboardEntry[] }) {
  return (
    <section>
      <PaperSectionHeading>leaderboard</PaperSectionHeading>
      <ul className="mt-4 divide-y divide-ink-hairline border-y border-ink-hairline">
        {entries.map((e) => (
          <li key={e.user_id} className="flex items-baseline justify-between gap-4 py-3">
            <div className="flex items-baseline gap-4">
              <span className="w-6 shrink-0 font-mono text-mini text-ink-muted">{e.rank}</span>
              <span className="font-mono text-sm text-ink">{e.display_name}</span>
            </div>
            <span className="shrink-0 font-mono uppercase tracking-mono-caps text-mini text-ink-muted">
              {e.vote_count} {e.vote_count === 1 ? "vote" : "votes"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
