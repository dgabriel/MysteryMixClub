import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  addNote,
  castVotes,
  deleteSubmission,
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
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { SongSearchCard } from "../components/songs/SongSearchCard";
import { SourceBadge } from "../components/SourceBadge";
import { AppleMusicPlaylist } from "../components/AppleMusicPlaylist";
import { SpotifyPlaylist } from "../components/SpotifyPlaylist";
import { SourceOnlyTracks, type SourceOnlyTrack } from "../components/SourceOnlyTracks";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { CrownIcon } from "../components/CrownIcon";
import { MedalIcon } from "../components/MedalIcon";
import { MusicNoteIcon } from "../components/MusicNoteIcon";
import { DeadlineChip } from "../components/DeadlineChip";
import { HelpLink } from "../components/HelpLink";
import { toDatetimeLocalValue } from "../utils/deadline";

const STATE_LABEL: Record<MixState, string> = {
  pending: "upcoming",
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "closed",
};

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
      setMessage(`this mystery mix is now ${STATE_LABEL[state]}`);
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
  // Per-mix "Just Vibes for this Mix" toggle (MYS-60), seeded from the
  // existing submission's mode, else the caller's per-club vibe setting.
  const [mixVibe, setMixVibe] = useState(false);
  const [playlist, setPlaylist] = useState<PlaylistEntry[]>([]);
  const [youtubePlaylistUrl, setYoutubePlaylistUrl] = useState<string | null>(null);
  const [youtubeTrackCount, setYoutubeTrackCount] = useState(0);
  // Voting progress (MYS-102): X of Y voted or noted · Z just vibing.
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
      setEditError(err instanceof ApiError ? err.message : "couldn't save the mystery mix. try again.");
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
      <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  if (error || !mix || !id) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-4 text-center sm:px-8">
        <p className="font-mono text-[13px] font-light text-muted">{error ?? "mystery mix not found."}</p>
        <div className="mt-6">
          <Button variant="ghost" type="button" onClick={() => navigate("/home")}>
            home
          </Button>
        </div>
      </main>
    );
  }

  return (
    <>
      {blocker.state === "blocked" ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4">
          <div className="w-full max-w-sm border border-border bg-cream p-6">
            <p className="font-mono text-[13px] font-light text-ink">
              you&apos;ve submitted {mySubmissions.length} of {submissionCap} songs. leave anyway?
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
      <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
        {club ? (
          <button
            type="button"
            onClick={() => navigate(`/clubs/${mix.club_id}`)}
            className="inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage transition-colors duration-150 hover:text-ink"
          >
            <span aria-hidden="true">←</span>
            {club.name}
          </button>
        ) : null}
        <span className="mt-3 block font-mono uppercase tracking-label text-[9px] text-muted">
          mystery mix {mix.mix_number}
        </span>
        <div className="mt-1 flex items-start justify-between gap-4">
          <h1 className="font-serif text-[32px] leading-tight text-ink">
            {mix.theme ?? `Mystery Mix ${mix.mix_number}`}
          </h1>
          <div className="shrink-0 pt-2">
            <Badge>{STATE_LABEL[mix.state]}</Badge>
          </div>
        </div>
        <MixStateAnnouncer state={mix.state} />
        {mix.description ? (
          <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-muted">
            {mix.description}
          </p>
        ) : null}

        {/* Prominent, phase-appropriate deadline chip (MYS-161) — viewer-local
            time plus a live countdown. Renders nothing for legacy mixes with
            no deadline set. */}
        <DeadlineChip mix={mix} className="mt-4" showCountdown />

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

        {actionError ? (
          <p role="alert" className="mt-6 font-mono text-[13px] text-ink">
            {actionError}
          </p>
        ) : null}
        {clubRepeatWarning && !actionError ? (
          <p className="mt-6 font-mono text-[13px] text-muted">
            this song was submitted in a previous mystery mix — submitted anyway.
          </p>
        ) : null}

        <section className="mt-10">
          {mix.state === "pending" ? (
            <p className="font-mono text-[13px] font-light text-muted">
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
              <ResultsSection results={results} userId={userId} />
            </>
          )}
        </section>
      </main>
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
}) {
  // Closing is the one forward transition that cascades and can't be undone
  // in-app (MYS-170) — gated behind an explicit second step. "open mix" /
  // "open voting" stay one-click; they're lower-risk and easy to reason about.
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
        ? "open voting"
        : "close mix";
  const busyLabel = next === "closed" ? "closing…" : "opening…";
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

  if (next === "closed" && confirmingClose) {
    return (
      <div className="mt-6 space-y-4 border-t border-border pt-6">
        <p className="font-mono text-[13px] font-light text-muted">
          {isFinalMix
            ? "this closes the mystery mix and completes the club. it can't be undone."
            : "this closes the mystery mix and opens the next one, starting its submission deadline. it can't be undone."}
        </p>
        <div className="flex items-center gap-4">
          <Button type="button" onClick={() => onAdvance(next)} disabled={advancing}>
            {advancing ? busyLabel : "yes, close mix"}
          </Button>
          <Button
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
      <div className="mt-6 space-y-4 border-t border-border pt-6">
        <p className="font-mono text-[13px] font-light text-muted">
          {totalVotes > 0
            ? `this reopens submissions with a fresh window and discards ${totalVotes} vote${totalVotes === 1 ? "" : "s"} already cast. it can't be undone.`
            : "this reopens submissions with a fresh window. it can't be undone."}
        </p>
        <div className="flex items-center gap-4">
          <Button type="button" onClick={onRollback} disabled={rollingBack}>
            {rollingBack ? "reopening…" : "yes, reopen submissions"}
          </Button>
          <Button
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
      <div className="mt-6 space-y-4 border-t border-border pt-6">
        <label htmlFor="extend-voting-deadline" className="block">
          <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
            new voting deadline (up to 48h later)
          </span>
          <input
            id="extend-voting-deadline"
            type="datetime-local"
            value={chosenDeadline}
            min={minDatetime}
            max={maxDatetime}
            onChange={(e) => setChosenDeadline(e.target.value)}
            disabled={extendingVoting}
            className="mt-2 w-full border-0 border-b border-ink bg-transparent px-0 py-1 font-mono text-[13px] font-light text-ink focus:border-sage focus:outline-none disabled:opacity-50"
          />
        </label>
        <div className="flex items-center gap-4">
          <Button
            type="button"
            onClick={handleSaveExtend}
            disabled={extendingVoting || !chosenDeadline}
          >
            {extendingVoting ? "saving…" : "save"}
          </Button>
          <Button
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

  // A mix can't open without a theme (MYS-211) — block the click rather than
  // let the organizer hit the server's 409. Only applies to "open mix" itself;
  // once a mix is open its theme is already locked in, so nothing later in
  // the lifecycle needs this check.
  const blockedByMissingTheme = state === "pending" && !hasTheme;

  return (
    <div className="mt-6 border-t border-border pt-6">
      <div className="flex items-center gap-4">
        <Button
          type="button"
          onClick={() => (next === "closed" ? setConfirmingClose(true) : onAdvance(next))}
          disabled={busy || blockedByMissingTheme}
        >
          {advancing ? busyLabel : label}
        </Button>
        {state === "open_voting" ? (
          <Button variant="ghost" type="button" onClick={openExtendPicker} disabled={busy}>
            extend voting
          </Button>
        ) : null}
        {state === "open_voting" ? (
          <Button
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
        <p className="mt-3 font-mono text-[13px] font-light text-muted">
          set a theme below before opening this mystery mix.
        </p>
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
 * No Rust on this screen: the single Rust signal is reserved elsewhere (the
 * closed-mix reveal).
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
        <Button variant="ghost" type="button" onClick={openForm}>
          edit mix
        </Button>
      </div>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      noValidate
      className="mt-6 space-y-6 border-t border-border pt-6"
    >
      <div>
        <TextField
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
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          description
        </span>
        <textarea
          id="edit-mix-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={saving}
          className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink bg-transparent px-0 py-1 font-mono text-[13px] font-light text-ink placeholder:text-muted focus:border-sage focus:outline-none disabled:opacity-50"
        />
      </label>

      {error ? (
        <p id="edit-mix-error" role="alert" className="font-mono text-[13px] text-ink">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-4">
        <Button type="submit" disabled={saving}>
          {saving ? "saving…" : "save"}
        </Button>
        <Button variant="ghost" type="button" onClick={() => setOpen(false)} disabled={saving}>
          cancel
        </Button>
      </div>
    </form>
  );
}

/**
 * Submission progress (MYS-101): "X of Y submitted" while a mix is open for
 * submissions, so members can see how many picks are in. A quiet muted label —
 * no Rust (this screen reserves its single Rust use for the voting/reveal
 * states). Renders nothing until the club's member count is known.
 */
function SubmissionProgress({ submitted, total }: { submitted: number; total: number }) {
  if (total <= 0) return null;
  return (
    <p
      role="status"
      aria-live="polite"
      className="mb-6 font-mono uppercase tracking-label text-[9px] text-muted"
    >
      {submitted} of {total} submitted
    </p>
  );
}

/** One of the player's submitted songs, with change/remove affordances. Stays in
 *  the Sage/Ink family — no Rust on the submission screen. */
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
  eyebrow: string;
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
    <Card>
      <span className="font-mono uppercase tracking-label text-[9px] text-muted">{eyebrow}</span>
      <h3 className="mt-1 font-serif text-[20px] leading-tight text-ink">{submission.title}</h3>
      {submission.artist ? (
        <p className="mt-1 font-mono text-[11px] font-light text-muted">{submission.artist}</p>
      ) : null}

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
            className="w-full resize-none border-b border-ink bg-transparent font-mono text-[13px] font-light text-ink placeholder:text-muted focus:border-sage focus:outline-none"
          />
          <div className="mt-2 flex items-center gap-4">
            <button
              type="button"
              disabled={savingNote}
              onClick={() => void handleNoteSave()}
              className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
            >
              {savingNote ? "saving…" : "save note"}
            </button>
            <button
              type="button"
              disabled={savingNote}
              onClick={() => setEditingNote(false)}
              className="font-mono uppercase tracking-ui text-[11px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
            >
              cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          {submission.note ? (
            <p className="mt-3 border-l-2 border-sage pl-3 font-mono text-[13px] font-light text-ink">
              &ldquo;{submission.note}&rdquo;
            </p>
          ) : null}
          <div className="mt-3">
            <button
              type="button"
              disabled={busy}
              onClick={openNoteEditor}
              className="font-mono uppercase tracking-ui text-[11px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
            >
              {submission.note ? "edit note" : "add a note"}
            </button>
          </div>
        </>
      )}

      <div className="mt-5 flex items-center gap-5">
        <button
          type="button"
          onClick={onEdit}
          disabled={busy}
          className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
        >
          change song
        </button>
        <button
          type="button"
          onClick={onRemove}
          disabled={busy}
          className="font-mono uppercase tracking-ui text-[11px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
        >
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
  heading: string;
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
          <Button variant="ghost" type="button" onClick={onCancel} disabled={submitting}>
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
 * The "just vibes" stance is a club-level setting chosen by the organizer at
 * club creation; there is no per-player toggle here, so the stance is uniform
 * across all of a player's songs.
 *
 * No Rust here — the mix screen reserves its single Rust signal for the
 * voting/reveal states.
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
        <h2 className="mb-4 font-mono uppercase tracking-label text-[9px] text-muted">
          your songs · {submissions.length} of {cap}
        </h2>
      ) : null}

      <ul className="space-y-4">
        {submissions.map((s, i) =>
          editingId === s.id ? (
            <li key={s.id}>
              <ComposerSlot
                heading={numbered ? `change song ${i + 1}` : "change your song"}
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
                eyebrow={numbered ? `song ${i + 1}` : "your song"}
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
                heading={numbered ? `submit song ${slot + 1}` : "submit a song"}
                idPrefix={`slot-${slot}`}
                submitting={submitting}
                onSubmit={onAdd}
              />
            </li>
          );
        })}
      </ul>

      {allSubmitted ? (
        <div className="mt-6 border-t border-border pt-6">
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
    <ul className="mt-3 flex flex-wrap gap-2">
      {available.map((p) => (
        <li key={p.key}>
          <a
            href={platforms[p.key as PlatformKey]}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`open ${title} on ${p.label} (opens in a new tab)`}
            className="inline-flex items-center rounded-[2px] border border-border px-2.5 py-1.5 font-mono uppercase tracking-ui text-[11px] text-ink transition-colors duration-150 hover:bg-sage-pale"
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
 * non-null). Stays firmly in the Sage/Ink family — a sage underline-style link,
 * no Rust (reserved for the voted-song outline) and no YouTube red. The subtle
 * count line tells the listener how much of the mix made it across.
 */
function YouTubePlaylistLink({
  youtubePlaylistUrl,
  youtubeTrackCount,
  entryCount,
}: {
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
  entryCount: number;
}) {
  if (!youtubePlaylistUrl) return null;
  return (
    <div className="mb-8">
      <a
        href={youtubePlaylistUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
      >
        <MusicNoteIcon />
        open playlist in YouTube
      </a>
      <span className="mt-1 block font-mono uppercase tracking-label text-[9px] text-muted">
        {youtubeTrackCount} of {entryCount} on YouTube
      </span>
    </div>
  );
}

/**
 * Voting progress (MYS-102): "X of Y voted or noted · Z just vibing". A quiet
 * muted label so the room can see how participation is filling in. No Rust —
 * the voting screen reserves its single Rust signal for the selected-vote
 * outline. Renders nothing until there are eligible (playing) voters.
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
    <p className="mb-6 font-mono uppercase tracking-label text-[9px] text-muted">
      {acted} of {eligible} voted or noted
      {vibing > 0 ? ` · ${vibing} just vibing` : ""}
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
): SourceOnlyTrack[] {
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
 * Stays in the Sage/Ink family — the reveal reserves its one Rust use for Most
 * Noted.
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
  sourceOnly: SourceOnlyTrack[];
}) {
  if (entryCount === 0) return null;
  return (
    <div className="mb-10">
      <h2 className="mb-4 font-mono uppercase tracking-label text-[9px] text-muted">listen back</h2>
      <YouTubePlaylistLink
        youtubePlaylistUrl={youtubePlaylistUrl}
        youtubeTrackCount={youtubeTrackCount}
        entryCount={entryCount}
      />
      <SourceOnlyTracks tracks={sourceOnly} />
      <SpotifyPlaylist mixId={mixId} />
      <AppleMusicPlaylist mixId={mixId} />
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
    return <VotingTally voteCounts={voteCounts} votesSaved={votesSaved} myVotes={myVotes} />;
  }

  if (entries.length === 0) {
    return <p className="font-mono text-[13px] font-light text-muted">no submissions yet</p>;
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
        <p className="font-mono text-[13px] font-light text-muted">
          you&apos;re just vibing this one, so you sit voting out — settle in and enjoy the mix.
        </p>
        <h2 className="mt-8 font-mono uppercase tracking-label text-[9px] text-muted">
          playlist ({entries.length})
        </h2>
        <div className="mt-4">
          <YouTubePlaylistLink
            youtubePlaylistUrl={youtubePlaylistUrl}
            youtubeTrackCount={youtubeTrackCount}
            entryCount={entries.length}
          />
          <SourceOnlyTracks tracks={toSourceOnly(entries)} />
          <SpotifyPlaylist mixId={mixId} />
          <AppleMusicPlaylist mixId={mixId} />
        </div>
        <ul className="mt-4 space-y-4">
          {entries.map((entry) => (
            <li key={entry.submission_id}>
              <Card>
                <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                {entry.artist ? (
                  <p className="mt-1 font-mono text-[11px] font-light text-muted">{entry.artist}</p>
                ) : null}
                {entry.source ? (
                  <div className="mt-2">
                    <SourceBadge source={entry.source} />
                  </div>
                ) : null}
                {entry.submitter_note ? (
                  <p className="mt-3 border-l-2 border-sage pl-3 font-mono text-[13px] font-light text-ink">
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
      <YouTubePlaylistLink
        youtubePlaylistUrl={youtubePlaylistUrl}
        youtubeTrackCount={youtubeTrackCount}
        entryCount={entries.length}
      />
      <SourceOnlyTracks tracks={toSourceOnly(entries)} />
      <SpotifyPlaylist mixId={mixId} />
      <AppleMusicPlaylist mixId={mixId} />
      <div className="flex items-baseline justify-between gap-4">
        <span className="flex items-center gap-2">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
            cast your votes
          </h2>
          <HelpLink anchor="voting-results" />
        </span>
        <span
          aria-live="polite"
          className="font-mono uppercase tracking-label text-[9px] text-muted"
        >
          {selected.length} / {votesPerPlayer} selected
        </span>
      </div>

      <ul className="mt-4 space-y-4">
        {entries.map((entry) => {
          // Your own song: shown in the playlist but never a vote toggle — you
          // can't vote for it (MYS-73), and it's clearly marked as yours
          // (MYS-74/75). No notes affordance either — you can't leave a note on
          // your own submission (MYS-77). Stays in the Sage/Ink family; Rust is
          // reserved for the songs you've voted for.
          if (entry.is_own) {
            return (
              <li key={entry.submission_id}>
                <div className="rounded-[3px] border border-border bg-sage-pale/40 px-6 py-5">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                    <span className="shrink-0">
                      <Badge>your submission</Badge>
                    </span>
                  </div>
                  {entry.artist ? (
                    <p className="mt-1 font-mono text-[11px] font-light text-sage">
                      {entry.artist}
                    </p>
                  ) : null}
                  {entry.source ? (
                    <div className="mt-2">
                      <SourceBadge source={entry.source} />
                    </div>
                  ) : null}
                  {entry.submitter_note ? (
                    <p className="mt-3 border-l-2 border-sage pl-3 font-mono text-[13px] font-light text-ink">
                      &ldquo;{entry.submitter_note}&rdquo;
                    </p>
                  ) : null}
                  <p className="mt-2 font-mono text-[11px] font-light text-sage">
                    you can&apos;t vote for your own song
                  </p>
                  <PlatformLinks
                  platforms={entry.platforms}
                  title={entry.title}
                  source={entry.source}
                />
                </div>
              </li>
            );
          }
          const isSelected = selected.includes(entry.submission_id);
          const disabled = !isSelected && atLimit;
          return (
            <li key={entry.submission_id}>
              {/* Card wrapper — owns the border/radius so notes can live inside
                  without nesting interactive elements inside the vote button. */}
              <div
                className={[
                  "rounded-[3px] border bg-white transition-colors duration-150",
                  isSelected ? "border-rust" : "border-border",
                  disabled ? "opacity-50" : "",
                ].join(" ")}
              >
                {/* Vote toggle — only the top portion of the card is clickable. */}
                <button
                  type="button"
                  aria-pressed={isSelected}
                  disabled={disabled}
                  onClick={() => toggle(entry.submission_id)}
                  className={[
                    "group block w-full px-6 pt-5 pb-3 text-left",
                    disabled ? "cursor-not-allowed" : "cursor-pointer",
                    !isSelected && !disabled ? "hover:bg-sage-pale/60" : "",
                  ].join(" ")}
                >
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                    <span className="shrink-0 pt-1 font-mono uppercase tracking-label text-[9px] text-rust">
                      {isSelected ? "voted" : ""}
                    </span>
                  </div>
                  {entry.artist ? (
                    <p className="mt-1 font-mono text-[11px] font-light text-muted group-hover:text-sage">
                      {entry.artist}
                    </p>
                  ) : null}
                  {entry.source ? (
                    <div className="mt-2">
                      <SourceBadge source={entry.source} />
                    </div>
                  ) : null}
                  {entry.submitter_note ? (
                    <p className="mt-3 border-l-2 border-sage pl-3 font-mono text-[13px] font-light text-ink">
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

      <div className="mt-6 border-t border-border pt-6">
        <Button
          type="button"
          onClick={() => onCast(selected)}
          disabled={casting || selected.length === 0}
        >
          {casting ? "casting…" : "cast votes"}
        </Button>
        {votesSaved ? (
          <p
            aria-live="polite"
            className="mt-3 font-mono uppercase tracking-label text-[9px] text-sage"
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
 */
function VotingTally({
  voteCounts,
  votesSaved,
  myVotes,
}: {
  voteCounts: VoteCountEntry[];
  votesSaved: boolean;
  myVotes: string[];
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
      <p className="font-mono text-[13px] font-light text-muted">
        you&apos;ve locked in your votes — check back to see how the voting goes.
      </p>
      <h2 className="mt-8 font-mono uppercase tracking-label text-[9px] text-muted">
        vote tally ({voteCounts.length} songs)
      </h2>
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
                "flex items-center justify-between rounded-[2px] border px-4 py-3",
                isVoted ? "border-sage bg-white" : "border-border bg-sage-pale/20",
              ].join(" ")}
            >
              <div className="flex items-center gap-3 overflow-hidden">
                <span
                  className={[
                    "w-6 shrink-0 font-mono text-[13px] font-light",
                    isVoted ? "text-muted" : "text-sage",
                  ].join(" ")}
                >
                  #{i + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p
                    className="font-serif text-[16px] leading-snug text-ink truncate"
                    title={entry.title}
                  >
                    {entry.title}
                  </p>
                  <p
                    className={[
                      "font-mono text-[11px] font-light leading-normal truncate",
                      isVoted ? "text-muted" : "text-sage",
                    ].join(" ")}
                  >
                    {entry.artist}
                  </p>
                </div>
              </div>
              <div className="shrink-0 text-right">
                <span className="block font-mono text-[13px] font-light text-ink">
                  {entry.vote_count} {entry.vote_count === 1 ? "vote" : "votes"}
                </span>
                {isVoted && (
                  <span className="inline-flex items-center gap-1 font-mono uppercase tracking-ui text-[9px] text-sage">
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
        <div className="mt-6 border-t border-border pt-6">
          <p className="font-mono uppercase tracking-label text-[9px] text-muted">
            your votes are locked — they will be revealed when the mystery mix closes
          </p>
        </div>
      )}
      {/* Show "votes saved" confirmation even when locked (after casting) */}
      {votesSaved && (
        <p
          aria-live="polite"
          className="mt-6 font-mono uppercase tracking-label text-[9px] text-sage"
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

  async function submit() {
    const body = draft.trim();
    if (!body || body.length > NOTE_MAX || posting) return;
    setPosting(true);
    onActionError(null);
    try {
      const created = await addNote(submissionId, body);
      setNotes((current) => [...current, created]);
      setLoaded(true);
      setDraft("");
      setComposing(false);
      setOpen(true);
    } catch (err) {
      onActionError(err instanceof ApiError ? err.message : "couldn't leave your note. try again.");
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
          className="font-mono uppercase tracking-ui text-[11px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
        >
          notes{loaded ? ` (${notes.length})` : ""}
        </button>
        {!composing ? (
          <button
            type="button"
            onClick={() => {
              setComposing(true);
              setOpen(true);
            }}
            className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
          >
            leave a note
          </button>
        ) : null}
      </div>

      {open ? (
        <>
          {composing ? (
            <div className="mt-4">
              {composerHint ? (
                <p className="font-mono text-[11px] font-light text-muted">{composerHint}</p>
              ) : null}
              <label className="mt-2 block">
                <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
                  your note
                </span>
                <textarea
                  value={draft}
                  maxLength={NOTE_MAX}
                  rows={2}
                  onChange={(e) => setDraft(e.target.value)}
                  className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink bg-transparent px-0 py-1 font-mono text-[13px] font-light text-ink placeholder:text-muted focus:border-sage focus:outline-none"
                />
              </label>
              <div className="mt-2 flex items-center justify-between gap-4">
                <span
                  aria-live="polite"
                  className="font-mono uppercase tracking-label text-[9px] text-muted"
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
                    className="font-mono uppercase tracking-ui text-[11px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
                  >
                    cancel
                  </button>
                  <Button type="button" onClick={() => void submit()} disabled={submitDisabled}>
                    {posting ? "posting…" : "leave note"}
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {loaded && notes.length > 0 ? (
            <ul className="mt-4 space-y-3 border-t border-border pt-4">
              {notes.map((note) => (
                <li key={note.id}>
                  <p className="font-mono text-[13px] font-light leading-relaxed text-ink">
                    {note.body}
                  </p>
                  <span className="mt-1 block font-mono uppercase tracking-label text-[9px] text-muted">
                    {note.author_display_name}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}

          {loaded && notes.length === 0 && !composing ? (
            <p className="mt-3 font-mono text-[11px] font-light text-muted">no notes yet</p>
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
          <p className="font-mono text-[13px] font-light leading-relaxed text-ink">{note.body}</p>
          <span className="mt-1 block font-mono uppercase tracking-label text-[9px] text-muted">
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
 * (MYS-112). Stays in the Sage/Ink family — no Rust, which the reveal reserves
 * for Most Noted (MYS-71).
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
    <div className="mt-4 border-t border-border pt-4">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="font-mono uppercase tracking-label text-[9px] text-muted underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
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
 * Noted (the one Rust signal on this screen), the Winner(s) by votes, the
 * Playing leaderboard, then a single ranked "the picks" list with every
 * submission's full detail (submitter, notes, platforms, voters) — the
 * standalone compact song-rank list was folded into this one to avoid listing
 * every song twice (MYS-173 follow-up). Top 3 ranks get a filled Sage badge
 * (RankBadge) so they read as distinct without a second Rust/Gold signal.
 */
function ResultsSection({
  results,
  userId,
}: {
  results: MixResults | null;
  userId: string | null;
}) {
  if (!results) {
    return <p className="font-mono text-[13px] font-light text-muted">no submissions</p>;
  }

  // A vibing viewer gets the trimmed reveal — winner(s) + Most Noted + their own
  // song's notes, no rankings or vote counts (MYS-112).
  if (results.viewer_is_vibing) {
    return <VibingReveal results={results} />;
  }

  if (results.submissions.length === 0) {
    return <p className="font-mono text-[13px] font-light text-muted">no submissions</p>;
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
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
            the picks ({submissions.length})
          </h2>
          <ul className="mt-4 space-y-4">
            {rankSongs(submissions).map((s) => (
              <li key={s.submission_id}>
                <Card>
                  <div className="flex items-start gap-4">
                    <RankBadge rank={s.rank} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                          {nameFor(s.user_id, s.submitter_display_name)}
                        </span>
                        <span className="flex shrink-0 flex-col items-end">
                          <span className="font-mono uppercase tracking-label text-[9px] text-sage">
                            {s.vote_count} {s.vote_count === 1 ? "vote" : "votes"}
                          </span>
                          {s.tied ? (
                            <span className="mt-0.5 font-mono uppercase tracking-label text-[9px] text-muted">
                              tied
                            </span>
                          ) : null}
                        </span>
                      </div>
                      <h3 className="mt-1 font-serif text-[18px] leading-tight text-ink">
                        {s.title}
                      </h3>
                      {s.artist ? (
                        <p className="mt-1 font-mono text-[11px] font-light text-muted">
                          {s.artist}
                        </p>
                      ) : null}
                      {s.source ? (
                        <div className="mt-2">
                          <SourceBadge source={s.source} />
                        </div>
                      ) : null}
                      {s.submitter_note ? (
                        <p className="mt-2 font-mono text-[11px] font-light text-ink">
                          “{s.submitter_note}”
                        </p>
                      ) : null}
                      <PlatformLinks platforms={s.platforms} title={s.title} source={s.source} />
                      {s.voters.length > 0 ? (
                        <p className="mt-2 font-mono text-[11px] font-light text-muted">
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

/** A song's rank within its mix. Top 3 get a filled Sage badge — the app's
 *  hierarchy color, not a new signal — so they read as distinct at a glance
 *  without competing with the Rust/Gold signals used elsewhere on this screen. */
function RankBadge({ rank }: { rank: number }) {
  if (rank > 3) {
    return (
      <span className="flex h-6 w-6 shrink-0 items-center justify-center font-mono text-[11px] text-muted">
        {rank}
      </span>
    );
  }
  // 1st place reads slightly larger than 2nd/3rd, and in Gold — the app's
  // existing achievement-signal color (crown icons above use it too) — since
  // this medal marks the same winner moment. The numeral sits inside the
  // medal's disc — centered on its (6, 4.5) midpoint in the icon's 0-12
  // viewBox, i.e. 50% across / 37.5% down the rendered icon.
  const first = rank === 1;
  return (
    <span
      className={["relative shrink-0", first ? "h-7 w-7 text-gold" : "h-6 w-6 text-sage"].join(" ")}
    >
      <MedalIcon className="h-full w-full" />
      {/* The numeral is real text (not decorative like the medal outline above),
          so it needs its own AA-contrast color — gold/sage-on-cream both fail
          WCAG 1.4.3 at this size (MYS-186). */}
      <span
        className={[
          "absolute left-1/2 top-[37.5%] -translate-x-1/2 -translate-y-1/2 font-mono leading-none text-ink",
          first ? "text-[12px]" : "text-[10px]",
        ].join(" ")}
      >
        {rank}
      </span>
    </span>
  );
}

/**
 * The reveal a vibing viewer sees (MYS-112 / MYS-134): Most Noted (the screen's
 * one Rust signal), the winner(s) by votes — named, no counts — and the full
 * tracklist with notes but NO scores or leaderboard.
 */
function VibingReveal({ results }: { results: MixResults }) {
  const { most_noted, winners, picks } = results;
  return (
    <div className="animate-fade-in space-y-12">
      {most_noted.winners.length > 0 ? <MostNotedSection winners={most_noted.winners} /> : null}

      {winners.length > 0 ? <VibeWinnersSection winners={winners} /> : null}

      {picks.length > 0 ? <VibePicksSection picks={picks} /> : null}
    </div>
  );
}

/** The winner(s) as shown to a vibing viewer — named, no vote counts. */
function VibeWinnersSection({ winners }: { winners: WinnerReveal[] }) {
  const tie = winners.length > 1;
  return (
    <section>
      <h2 className="inline-flex items-center gap-1.5 font-mono uppercase tracking-label text-[9px] text-muted">
        <CrownIcon className="text-gold" />
        {tie ? "winners" : "winner"}
      </h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        {tie ? "the most-loved picks this mystery mix" : "the most-loved pick this mystery mix"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.submission_id}>
            <Card>
              <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                {w.submitter_display_name ?? "someone"}
              </span>
              <h3 className="mt-1 font-serif text-[24px] leading-tight text-ink">{w.title}</h3>
              {w.artist ? (
                <p className="mt-1 font-mono text-[11px] font-light text-muted">{w.artist}</p>
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
 *  what was in the mix without any scores. */
function VibePicksSection({ picks }: { picks: RevealPick[] }) {
  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        the picks ({picks.length})
      </h2>
      <ul className="mt-4 space-y-4">
        {picks.map((p) => (
          <li key={p.submission_id}>
            <Card>
              <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                {p.submitter_display_name ?? "someone"}
              </span>
              <h3 className="mt-1 font-serif text-[18px] leading-tight text-ink">{p.title}</h3>
              {p.artist ? (
                <p className="mt-1 font-mono text-[11px] font-light text-muted">{p.artist}</p>
              ) : null}
              {p.source ? (
                <div className="mt-2">
                  <SourceBadge source={p.source} />
                </div>
              ) : null}
              {p.submitter_note ? (
                <p className="mt-2 font-mono text-[11px] font-light text-ink">
                  “{p.submitter_note}”
                </p>
              ) : null}
              <PlatformLinks platforms={p.platforms} title={p.title} source={p.source} />
              {p.notes.length > 0 ? <CollapsibleNotes notes={p.notes} /> : null}
            </Card>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The single most important element on the reveal — the song(s) that drew the
 * most notes. This is the screen's one Rust use: the Card's Rust left accent
 * bar. A tie shows every winner as co-recognized.
 */
function MostNotedSection({ winners }: { winners: MostNotedWinner[] }) {
  const tie = winners.length > 1;
  return (
    <section>
      <h2 className="inline-flex items-center gap-1.5 font-mono uppercase tracking-label text-[9px] text-muted">
        <CrownIcon className="text-gold" />
        most noted
      </h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        {tie ? "the picks that got everyone talking" : "the pick that got everyone talking"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.submission_id}>
            {/* Rust accent bar — the one Rust signal on this screen. */}
            <Card accent>
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-serif text-[24px] leading-tight text-ink">{w.title}</h3>
                <span className="shrink-0 pt-1 font-mono uppercase tracking-label text-[9px] text-muted">
                  {w.note_count} {w.note_count === 1 ? "note" : "notes"}
                </span>
              </div>
              {w.artist ? (
                <p className="mt-1 font-mono text-[11px] font-light text-muted">{w.artist}</p>
              ) : null}
              {w.notes.length > 0 ? (
                <div className="mt-5 border-t border-border pt-5">
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
 * The mix's winner(s) by votes — prominent but secondary to Most Noted (no
 * Rust accent here, so Most Noted keeps the screen's single Rust signal). A tie
 * co-recognizes every top-voted pick.
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
      <h2 className="inline-flex items-center gap-1.5 font-mono uppercase tracking-label text-[9px] text-muted">
        <CrownIcon className="text-gold" />
        {tie ? "winners" : "winner"}
      </h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        {tie ? "tied for the most votes this mystery mix" : "the most votes this mystery mix"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.userId}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                  {nameFor(w.userId, w.displayName)}
                </span>
                {/* The per-player total — the score the leaderboard ranks on. */}
                <span className="shrink-0 pt-1 font-mono uppercase tracking-label text-[9px] text-sage">
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
                    <div key={s.submission_id} className={i === 0 ? "mt-1" : "mt-3"}>
                      <h3 className="font-serif text-[24px] leading-tight text-ink">{s.title}</h3>
                      {s.artist ? (
                        <p className="mt-1 font-mono text-[11px] font-light text-muted">
                          {s.artist}
                        </p>
                      ) : null}
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

/** The Playing leaderboard — already ranked, vibing excluded. Calm and compact;
 *  no Rust (rank #1 included stays in the Sage/Ink family). */
function LeaderboardSection({ entries }: { entries: LeaderboardEntry[] }) {
  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">leaderboard</h2>
      <ul className="mt-4 divide-y divide-border border-y border-border">
        {entries.map((e) => (
          <li key={e.user_id} className="flex items-baseline justify-between gap-4 py-3">
            <div className="flex items-baseline gap-4">
              <span className="w-6 shrink-0 font-mono text-[13px] font-light text-muted">
                {e.rank}
              </span>
              <span className="font-mono text-[13px] font-light text-ink">{e.display_name}</span>
            </div>
            <span className="shrink-0 font-mono uppercase tracking-label text-[9px] text-sage">
              {e.vote_count} {e.vote_count === 1 ? "vote" : "votes"}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
