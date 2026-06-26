import { type FormEvent, useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  addNote,
  castVotes,
  getLeague,
  getMyMembership,
  getMySubmission,
  getMyVotes,
  getNotes,
  getPlaylist,
  getResults,
  getRound,
  submitSong,
  updateRound,
  type League,
  type LeaderboardEntry,
  type MostNotedWinner,
  type Note,
  type OwnSubmissionReveal,
  type PlaylistEntry,
  type ResolvedSong,
  type ResultNote,
  type ResultSubmission,
  type Round,
  type RoundResults,
  type RoundState,
  type SubmissionResult,
  type WinnerReveal,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { SongSearchCard } from "../components/songs/SongSearchCard";
import { SpotifyPlaylist } from "../components/SpotifyPlaylist";

const STATE_LABEL: Record<RoundState, string> = {
  pending: "upcoming",
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "closed",
};

const PLATFORM_LABELS: { key: string; label: string }[] = [
  { key: "spotify", label: "Spotify" },
  { key: "appleMusic", label: "Apple Music" },
  { key: "deezer", label: "Deezer" },
  { key: "youtube", label: "YouTube" },
];

/**
 * Round detail (`/rounds/:id`). State-aware:
 *  - open_submission → submit/replace your song (organizer can open voting)
 *  - open_voting     → the anonymous, shuffled playlist (organizer can close)
 *  - closed          → revealed submissions
 * Self-contained: loads the round + league (for organizer/name) plus the
 * state-specific data, and wires submit / advance back to the API.
 */
export function RoundDetailRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [round, setRound] = useState<Round | null>(null);
  const [league, setLeague] = useState<League | null>(null);
  const [mine, setMine] = useState<SubmissionResult | null>(null);
  // Per-round "Just Vibes for this Round" toggle (MYS-60), seeded from the
  // existing submission's mode, else the caller's per-league vibe setting.
  const [roundVibe, setRoundVibe] = useState(false);
  const [playlist, setPlaylist] = useState<PlaylistEntry[]>([]);
  const [youtubePlaylistUrl, setYoutubePlaylistUrl] = useState<string | null>(null);
  const [youtubeTrackCount, setYoutubeTrackCount] = useState(0);
  // Voting progress (MYS-102): X of Y voted or noted · Z just vibing.
  const [votingEligible, setVotingEligible] = useState(0);
  const [votingActed, setVotingActed] = useState(0);
  const [vibingCount, setVibingCount] = useState(0);
  const [myVotes, setMyVotes] = useState<string[]>([]);
  const [results, setResults] = useState<RoundResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [advancing, setAdvancing] = useState(false);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [casting, setCasting] = useState(false);
  const [votesSaved, setVotesSaved] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const loadedRound = await getRound(id);
      const loadedLeague = await getLeague(loadedRound.league_id);
      setRound(loadedRound);
      setLeague(loadedLeague);

      if (loadedRound.state === "pending") {
        // Nothing to load yet — the round isn't open. The organizer can edit its
        // theme/description and open it from here.
      } else if (loadedRound.state === "open_submission") {
        const [loadedMine, membership] = await Promise.all([
          getMySubmission(id),
          getMyMembership(loadedRound.league_id),
        ]);
        setMine(loadedMine);
        // Seed the round toggle: an existing submission's mode wins, else the
        // member's per-league default.
        setRoundVibe(
          loadedMine ? loadedMine.participation_mode === "vibing" : membership.vibe_mode,
        );
      } else if (loadedRound.state === "open_voting") {
        const [loadedPlaylist, loadedVotes, loadedMine] = await Promise.all([
          getPlaylist(id),
          getMyVotes(id),
          getMySubmission(id),
        ]);
        setPlaylist(loadedPlaylist.entries);
        setYoutubePlaylistUrl(loadedPlaylist.youtube_playlist_url);
        setYoutubeTrackCount(loadedPlaylist.youtube_track_count);
        setVotingEligible(loadedPlaylist.voting_eligible);
        setVotingActed(loadedPlaylist.voting_acted);
        setVibingCount(loadedPlaylist.vibing_count);
        setMyVotes(loadedVotes.submission_ids);
        setMine(loadedMine);
      } else {
        // Closed: the reveal plus a way to still listen to the mix (MYS-133).
        // The playlist endpoint serves closed rounds too.
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
      setError(err instanceof ApiError ? err.message : "couldn't load this round.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const isOrganizer = !!userId && !!league && league.organizer_id === userId;

  async function handleSubmit(song: ResolvedSong) {
    if (!id || !song.isrc) {
      setActionError("this song is missing an ID and can't be submitted.");
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const result = await submitSong(id, {
        title: song.title,
        artist: song.artist ?? "",
        isrc: song.isrc,
        album: song.album,
        album_art_url: song.thumbnail_url,
        participation_mode: roundVibe ? "vibing" : "playing",
      });
      setMine(result);
      // Refresh the round so "X of Y submitted" reflects this submission right
      // away (MYS-101). Refetch rather than locally increment so a *replacement*
      // (which doesn't change the count) stays correct too. Non-fatal: the
      // submission already saved; only the counter would lag.
      try {
        setRound(await getRound(id));
      } catch {
        // leave the counter as-is; the submission itself succeeded.
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't submit. try again.");
    } finally {
      setSubmitting(false);
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
      } catch {
        // leave the counter as-is; the cast itself succeeded.
      }
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "couldn't save your votes. try again.",
      );
    } finally {
      setCasting(false);
    }
  }

  async function handleEditRound(input: { theme?: string | null; description?: string | null }) {
    if (!id) return;
    setSavingEdit(true);
    setEditError(null);
    try {
      const updated = await updateRound(id, input);
      setRound(updated);
      return true;
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : "couldn't save the round. try again.");
      return false;
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleAdvance(next: RoundState) {
    if (!id) return;
    setAdvancing(true);
    setActionError(null);
    try {
      await updateRound(id, { state: next });
      await load();
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : "couldn't update the round.");
    } finally {
      // Reset on success too — otherwise the button sticks on "opening…" after
      // the round has opened (MYS-95).
      setAdvancing(false);
    }
  }

  if (loading) {
    return (
      <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  if (error || !round || !id) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-4 text-center sm:px-8">
        <p className="font-mono text-[13px] font-light text-muted">{error ?? "round not found."}</p>
        <div className="mt-6">
          <Button variant="ghost" type="button" onClick={() => navigate("/home")}>
            home
          </Button>
        </div>
      </main>
    );
  }

  return (
    // Content-only: the shared TopNav is rendered once by AuthedLayout. The
    // round's league is reached via a named link above the title (not a generic
    // "← league" in the nav), so members always see which league they're in.
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      {league ? (
        <button
          type="button"
          onClick={() => navigate(`/leagues/${round.league_id}`)}
          className="inline-flex items-center gap-1.5 font-mono uppercase tracking-ui text-[11px] text-sage transition-colors duration-150 hover:text-ink"
        >
          <span aria-hidden="true">←</span>
          {league.name}
        </button>
      ) : null}
      <span className="mt-3 block font-mono uppercase tracking-label text-[9px] text-muted">
        round {round.round_number}
      </span>
      <div className="mt-1 flex items-start justify-between gap-4">
          <h1 className="font-serif text-[32px] leading-tight text-ink">
            {round.theme ?? `Round ${round.round_number}`}
          </h1>
          <div className="shrink-0 pt-2">
            <Badge>{STATE_LABEL[round.state]}</Badge>
          </div>
        </div>
        {round.description ? (
          <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-muted">
            {round.description}
          </p>
        ) : null}

        {isOrganizer ? (
          <>
            <OrganizerControls
              state={round.state}
              advancing={advancing}
              onAdvance={handleAdvance}
            />
            <EditRoundForm
              round={round}
              saving={savingEdit}
              error={editError}
              onSave={handleEditRound}
              onDismissError={() => setEditError(null)}
            />
          </>
        ) : null}

        {actionError ? (
          <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
            {actionError}
          </p>
        ) : null}

        <section className="mt-10">
          {round.state === "pending" ? (
            <p className="font-mono text-[13px] font-light text-muted">
              this round hasn&apos;t opened yet.
            </p>
          ) : round.state === "open_submission" ? (
            <>
              <SubmissionProgress
                submitted={round.submission_count}
                total={round.member_count}
              />
              <SubmissionSection
                mine={mine}
                submitting={submitting}
                roundVibe={roundVibe}
                onRoundVibeChange={setRoundVibe}
                onSubmit={handleSubmit}
                onChange={() => setMine(null)}
              />
            </>
          ) : round.state === "open_voting" ? (
            <VotingSection
              // Remount to re-seed the selection whenever the saved votes change.
              key={myVotes.join(",")}
              roundId={id}
              entries={playlist}
              youtubePlaylistUrl={youtubePlaylistUrl}
              youtubeTrackCount={youtubeTrackCount}
              votingEligible={votingEligible}
              votingActed={votingActed}
              vibingCount={vibingCount}
              votesPerPlayer={round.votes_per_player}
              myVotes={myVotes}
              isVibingParticipant={mine?.participation_mode === "vibing"}
              casting={casting}
              votesSaved={votesSaved}
              onCast={handleCastVotes}
              onSelectionChange={() => setVotesSaved(false)}
              onActionError={setActionError}
            />
          ) : (
            <>
              {/* Closed rounds keep a way to listen to the mix (MYS-133). */}
              <ClosedListen
                roundId={id}
                youtubePlaylistUrl={youtubePlaylistUrl}
                youtubeTrackCount={youtubeTrackCount}
                entryCount={playlist.length}
              />
              <ResultsSection results={results} userId={userId} />
            </>
          )}
        </section>
    </main>
  );
}

function OrganizerControls({
  state,
  advancing,
  onAdvance,
}: {
  state: RoundState;
  advancing: boolean;
  onAdvance: (next: RoundState) => void;
}) {
  if (state === "closed") return null;
  const next: RoundState =
    state === "pending"
      ? "open_submission"
      : state === "open_submission"
        ? "open_voting"
        : "closed";
  const label =
    state === "pending"
      ? "open round"
      : state === "open_submission"
        ? "open voting"
        : "close round";
  const busyLabel = next === "closed" ? "closing…" : "opening…";
  return (
    <div className="mt-6 border-t border-border pt-6">
      <Button type="button" onClick={() => onAdvance(next)} disabled={advancing}>
        {advancing ? busyLabel : label}
      </Button>
    </div>
  );
}

/**
 * Organizer round editor. Theme and description are the round's identity — the
 * API allows editing them ONLY while the round is `pending` (409 otherwise).
 * Once the round opens there's nothing left to edit here, so the affordance
 * simply doesn't render for non-pending rounds.
 *
 * No Rust on this screen: the single Rust signal is reserved elsewhere (the
 * closed-round reveal).
 */
function EditRoundForm({
  round,
  saving,
  error,
  onSave,
  onDismissError,
}: {
  round: Round;
  saving: boolean;
  error?: string | null;
  onSave: (input: {
    theme?: string | null;
    description?: string | null;
  }) => Promise<boolean | undefined>;
  onDismissError: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState(round.theme ?? "");
  const [description, setDescription] = useState(round.description ?? "");

  // Theme/description are only editable while the round is still `pending`;
  // once it opens there's nothing left to edit, so don't render the affordance.
  if (round.state !== "pending") return null;

  function openForm() {
    setTheme(round.theme ?? "");
    setDescription(round.description ?? "");
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
    // unnamed round can be saved back to unnamed.
    const trimmedTheme = theme.trim();
    const currentTheme = round.theme ?? "";
    if (trimmedTheme !== currentTheme) {
      input.theme = trimmedTheme ? trimmedTheme : null;
    }

    const trimmedDescription = description.trim();
    const currentDescription = round.description ?? "";
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
          edit round
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6 space-y-6 border-t border-border pt-6">
      <div>
        <TextField
          id="edit-round-theme"
          label="theme"
          name="theme"
          value={theme}
          onChange={(e) => setTheme(e.target.value)}
          disabled={saving}
          autoComplete="off"
        />
      </div>

      <label htmlFor="edit-round-description" className="block">
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          description
        </span>
        <textarea
          id="edit-round-description"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={saving}
          className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink bg-transparent px-0 py-1 font-mono text-[13px] font-light text-ink placeholder:text-muted focus:border-sage focus:outline-none disabled:opacity-50"
        />
      </label>

      {error ? (
        <p role="alert" className="font-mono text-[11px] text-ink">
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
 * Submission progress (MYS-101): "X of Y submitted" while a round is open for
 * submissions, so members can see how many picks are in. A quiet muted label —
 * no Rust (this screen reserves its single Rust use for the voting/reveal
 * states). Renders nothing until the league's member count is known.
 */
function SubmissionProgress({ submitted, total }: { submitted: number; total: number }) {
  if (total <= 0) return null;
  return (
    <p className="mb-6 font-mono uppercase tracking-label text-[9px] text-muted">
      {submitted} of {total} submitted
    </p>
  );
}

function SubmissionSection({
  mine,
  submitting,
  roundVibe,
  onRoundVibeChange,
  onSubmit,
  onChange,
}: {
  mine: SubmissionResult | null;
  submitting: boolean;
  roundVibe: boolean;
  onRoundVibeChange: (next: boolean) => void;
  onSubmit: (song: ResolvedSong) => void;
  onChange: () => void;
}) {
  if (mine) {
    return (
      <Card>
        <span className="font-mono uppercase tracking-label text-[9px] text-muted">
          your submission
        </span>
        <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">{mine.title}</h2>
        {mine.artist ? (
          <p className="mt-1 font-mono text-[11px] font-light text-muted">{mine.artist}</p>
        ) : null}
        <div className="mt-3">
          <Badge>{mine.participation_mode}</Badge>
        </div>
        <button
          type="button"
          onClick={onChange}
          className="mt-5 font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
        >
          change song
        </button>
      </Card>
    );
  }
  return (
    <>
      {/* Per-round override (MYS-60). Defaults from the member's per-league
          setting; flipping it changes only this round's submission. */}
      <div className="mb-6">
        <label className="flex cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            checked={roundVibe}
            onChange={(e) => onRoundVibeChange(e.target.checked)}
            disabled={submitting}
            className="h-4 w-4 rounded-[2px] border border-ink accent-sage"
          />
          <span className="font-mono uppercase tracking-ui text-[11px] text-ink">
            just vibes for this round
          </span>
        </label>
        <p className="mt-2 font-mono text-[11px] font-light text-muted">
          vibing means you sit out voting on this round and leave notes instead.
        </p>
      </div>
      <SongSearchCard
        eyebrow="this round"
        heading="submit a song"
        onSubmit={onSubmit}
        submitting={submitting}
      />
    </>
  );
}

function PlatformLinks({ entry }: { entry: PlaylistEntry }) {
  const available = PLATFORM_LABELS.filter(
    (p) => entry.platforms[p.key as keyof typeof entry.platforms],
  );
  return (
    <ul className="mt-3 flex flex-wrap gap-2">
      {available.map((p) => (
        <li key={p.key}>
          <a
            href={entry.platforms[p.key as keyof typeof entry.platforms]}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`open ${entry.title} on ${p.label} (opens in a new tab)`}
            className="inline-flex items-center rounded-[2px] border border-border px-2.5 py-1 font-mono uppercase tracking-ui text-[11px] text-ink transition-colors duration-150 hover:bg-sage-pale"
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
        className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
      >
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

/**
 * Listen affordance for a closed round (MYS-133): the whole-mix YouTube +
 * Spotify links, so members can still play the round after it closes. Reuses the
 * voting-screen components; renders nothing when the round had no submissions.
 * Stays in the Sage/Ink family — the reveal reserves its one Rust use for Most
 * Noted.
 */
function ClosedListen({
  roundId,
  youtubePlaylistUrl,
  youtubeTrackCount,
  entryCount,
}: {
  roundId: string;
  youtubePlaylistUrl: string | null;
  youtubeTrackCount: number;
  entryCount: number;
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
      <SpotifyPlaylist roundId={roundId} entryCount={entryCount} />
    </div>
  );
}

function VotingSection({
  roundId,
  entries,
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
  roundId: string;
  entries: PlaylistEntry[];
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
          you&apos;re just vibing this round, so you sit voting out — settle in and enjoy the mix.
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
          <SpotifyPlaylist roundId={roundId} entryCount={entries.length} />
        </div>
        <ul className="mt-4 space-y-4">
          {entries.map((entry) => (
            <li key={entry.submission_id}>
              <Card>
                <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                {entry.artist ? (
                  <p className="mt-1 font-mono text-[11px] font-light text-muted">{entry.artist}</p>
                ) : null}
                <PlatformLinks entry={entry} />
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
      <SpotifyPlaylist roundId={roundId} entryCount={entries.length} />
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
          cast your votes
        </h2>
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
                <div className="block w-full rounded-[3px] border border-border bg-sage-pale/40 px-6 py-5 text-left">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                    <span className="shrink-0">
                      <Badge>your submission</Badge>
                    </span>
                  </div>
                  {entry.artist ? (
                    <p className="mt-1 font-mono text-[11px] font-light text-muted">
                      {entry.artist}
                    </p>
                  ) : null}
                  <p className="mt-2 font-mono text-[11px] font-light text-muted">
                    you can&apos;t vote for your own song
                  </p>
                </div>
                <PlatformLinks entry={entry} />
              </li>
            );
          }
          const isSelected = selected.includes(entry.submission_id);
          const disabled = !isSelected && atLimit;
          return (
            <li key={entry.submission_id}>
              <button
                type="button"
                aria-pressed={isSelected}
                disabled={disabled}
                onClick={() => toggle(entry.submission_id)}
                className={[
                  "block w-full rounded-[3px] border bg-white px-6 py-5 text-left transition-colors duration-150",
                  // A selected song wears the screen's one Rust signal: a Rust
                  // outline marks the picks you've chosen to vote for. No other
                  // element on the voting screen uses Rust.
                  isSelected ? "border-rust" : "border-border hover:bg-sage-pale/60",
                  disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
                ].join(" ")}
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="font-serif text-[18px] leading-tight text-ink">{entry.title}</h3>
                  <span className="shrink-0 pt-1 font-mono uppercase tracking-label text-[9px] text-rust">
                    {isSelected ? "voted" : ""}
                  </span>
                </div>
                {entry.artist ? (
                  <p className="mt-1 font-mono text-[11px] font-light text-muted">{entry.artist}</p>
                ) : null}
              </button>
              <PlatformLinks entry={entry} />
              <SongNotes submissionId={entry.submission_id} onActionError={onActionError} />
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

/**
 * The winning song(s) of the round — the most votes. A tie shows every winner.
 * Returns [] when nobody drew a vote. Every submitter competes, vibers included
 * (MYS-112). This stays in the Sage/Ink family — no Rust, which the reveal
 * reserves for Most Noted (MYS-71).
 */
function topVotedSubmissions(submissions: ResultSubmission[]): ResultSubmission[] {
  const top = submissions.reduce((max, s) => Math.max(max, s.vote_count), 0);
  if (top <= 0) return [];
  return submissions.filter((s) => s.vote_count === top);
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
 * Closed-round reveal (MYS-24 / MYS-71). A static results moment — subtle
 * fade-in only, no staged animation (deferred to MYS-54). Top to bottom: Most
 * Noted (the one Rust signal on this screen), the Winner(s) by votes, the
 * Playing leaderboard, then every submission with its submitter revealed.
 * Vibing picks are shown fully and equally — a calm badge, never a score.
 */
function ResultsSection({
  results,
  userId,
}: {
  results: RoundResults | null;
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
  const nameFor = (s: ResultSubmission) =>
    s.user_id === userId ? "you" : (s.submitter_display_name ?? "someone");
  const winners = topVotedSubmissions(submissions);

  return (
    <div className="animate-fade-in space-y-12">
      {most_noted.winners.length > 0 ? <MostNotedSection winners={most_noted.winners} /> : null}

      {winners.length > 0 ? <WinnersSection winners={winners} nameFor={nameFor} /> : null}

      {leaderboard.length > 0 ? <LeaderboardSection entries={leaderboard} /> : null}

      <section>
        <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
          the picks ({submissions.length})
        </h2>
        <ul className="mt-4 space-y-4">
          {submissions.map((s) => (
            <li key={s.submission_id}>
              <Card>
                <div className="flex items-start justify-between gap-3">
                  <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                    {nameFor(s)}
                  </span>
                  <span className="shrink-0 font-mono uppercase tracking-label text-[9px] text-sage">
                    {s.vote_count} {s.vote_count === 1 ? "vote" : "votes"}
                  </span>
                </div>
                <h3 className="mt-1 font-serif text-[18px] leading-tight text-ink">{s.title}</h3>
                {s.artist ? (
                  <p className="mt-1 font-mono text-[11px] font-light text-muted">{s.artist}</p>
                ) : null}
                {s.submitter_note ? (
                  <p className="mt-2 font-mono text-[11px] font-light text-ink">
                    “{s.submitter_note}”
                  </p>
                ) : null}
                {s.notes.length > 0 ? <CollapsibleNotes notes={s.notes} /> : null}
              </Card>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

/**
 * The trimmed reveal a vibing viewer sees (MYS-112): Most Noted (the screen's one
 * Rust signal), the winner(s) by votes — named, no counts — and their own song's
 * notes so the appreciation lands. No leaderboard, no picks list, no vote tallies.
 */
function VibingReveal({ results }: { results: RoundResults }) {
  const { most_noted, winners, own_submission } = results;
  return (
    <div className="animate-fade-in space-y-12">
      {most_noted.winners.length > 0 ? <MostNotedSection winners={most_noted.winners} /> : null}

      {winners.length > 0 ? <VibeWinnersSection winners={winners} /> : null}

      {own_submission ? <OwnSubmissionSection own={own_submission} /> : null}
    </div>
  );
}

/** The winner(s) as shown to a vibing viewer — named, no vote counts. */
function VibeWinnersSection({ winners }: { winners: WinnerReveal[] }) {
  const tie = winners.length > 1;
  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        {tie ? "winners" : "winner"}
      </h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        {tie ? "the most-loved picks this round" : "the most-loved pick this round"}
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

/** A vibing viewer's own song with the notes it drew — the appreciation mechanic
 *  (MYS-112), no score attached. */
function OwnSubmissionSection({ own }: { own: OwnSubmissionReveal }) {
  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">your song</h2>
      <div className="mt-4">
        <Card>
          <h3 className="font-serif text-[18px] leading-tight text-ink">{own.title}</h3>
          {own.artist ? (
            <p className="mt-1 font-mono text-[11px] font-light text-muted">{own.artist}</p>
          ) : null}
          {own.submitter_note ? (
            <p className="mt-2 font-mono text-[11px] font-light text-ink">“{own.submitter_note}”</p>
          ) : null}
          {own.notes.length > 0 ? (
            <div className="mt-4 border-t border-border pt-4">
              <ResultNoteList notes={own.notes} />
            </div>
          ) : (
            <p className="mt-3 font-mono text-[11px] font-light text-muted">no notes yet</p>
          )}
        </Card>
      </div>
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
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">most noted</h2>
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
 * The round's winner(s) by votes — prominent but secondary to Most Noted (no
 * Rust accent here, so Most Noted keeps the screen's single Rust signal). A tie
 * co-recognizes every top-voted pick.
 */
function WinnersSection({
  winners,
  nameFor,
}: {
  winners: ResultSubmission[];
  nameFor: (s: ResultSubmission) => string;
}) {
  const tie = winners.length > 1;
  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        {tie ? "winners" : "winner"}
      </h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        {tie ? "tied for the most votes this round" : "the most votes this round"}
      </p>
      <ul className="mt-4 space-y-4">
        {winners.map((w) => (
          <li key={w.submission_id}>
            <Card>
              <div className="flex items-start justify-between gap-3">
                <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                  {nameFor(w)}
                </span>
                <span className="shrink-0 pt-1 font-mono uppercase tracking-label text-[9px] text-sage">
                  {w.vote_count} {w.vote_count === 1 ? "vote" : "votes"}
                </span>
              </div>
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
