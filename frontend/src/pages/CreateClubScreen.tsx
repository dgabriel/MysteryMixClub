import { type FormEvent, useState } from "react";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { DeadlineWindowField } from "../components/DeadlineWindowField";
import { HelpLink } from "../components/HelpLink";
import { daysAndHoursToTotal, validateWindowHours } from "../utils/deadlineWindow";

type CreateClubInput = {
  name: string;
  description?: string;
  total_mixes: number;
  votes_per_player: number;
  songs_per_submission: number;
  default_vibe_mode: boolean;
  submission_window_hours: number;
  voting_window_hours: number;
};

// Default window: 3 days 0 hours (72h) each, matching the API default.
const DEFAULT_WINDOW_DAYS = "3";
const DEFAULT_WINDOW_HOURS = "0";

type CreateClubScreenProps = {
  onSubmit: (input: CreateClubInput) => void;
  submitting: boolean;
  error?: string | null;
  onCancel: () => void;
};

export function CreateClubScreen({
  onSubmit,
  submitting,
  error,
  onCancel,
}: CreateClubScreenProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [totalMixes, setTotalMixes] = useState("6");
  const [votesPerPlayer, setVotesPerPlayer] = useState("3");
  const [songsPerSubmission, setSongsPerSubmission] = useState("1");
  const [defaultVibeMode, setDefaultVibeMode] = useState(false);
  const [submissionWindowDays, setSubmissionWindowDays] = useState(DEFAULT_WINDOW_DAYS);
  const [submissionWindowHours, setSubmissionWindowHours] = useState(DEFAULT_WINDOW_HOURS);
  const [votingWindowDays, setVotingWindowDays] = useState(DEFAULT_WINDOW_DAYS);
  const [votingWindowHours, setVotingWindowHours] = useState(DEFAULT_WINDOW_HOURS);
  const [guard, setGuard] = useState<string | null>(null);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmedName = name.trim();
    const mixes = Number(totalMixes);
    const votes = Number(votesPerPlayer);
    const songs = Number(songsPerSubmission);
    const submissionHours = daysAndHoursToTotal(
      Number(submissionWindowDays),
      Number(submissionWindowHours),
    );
    const votingHours = daysAndHoursToTotal(Number(votingWindowDays), Number(votingWindowHours));

    if (!trimmedName) {
      setGuard("a club needs a name.");
      return;
    }
    if (!Number.isFinite(mixes) || mixes < 1) {
      setGuard("a club needs at least one mystery mix.");
      return;
    }
    if (!Number.isFinite(votes) || votes < 1) {
      setGuard("votes per player must be at least 1.");
      return;
    }
    if (!Number.isFinite(songs) || songs < 1 || songs > 5) {
      setGuard("songs per submission must be between 1 and 5.");
      return;
    }
    const submissionWindowError = validateWindowHours(submissionHours);
    if (submissionWindowError) {
      setGuard(`submission ${submissionWindowError}`);
      return;
    }
    const votingWindowError = validateWindowHours(votingHours);
    if (votingWindowError) {
      setGuard(`voting ${votingWindowError}`);
      return;
    }

    setGuard(null);
    const trimmedDescription = description.trim();
    onSubmit({
      name: trimmedName,
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
      total_mixes: mixes,
      votes_per_player: votes,
      songs_per_submission: songs,
      default_vibe_mode: defaultVibeMode,
      submission_window_hours: submissionHours,
      voting_window_hours: votingHours,
    });
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-8 sm:px-8">
      <div className="w-full max-w-sm">
        {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">new club</h1>

        <form onSubmit={handleSubmit} className="mt-10 space-y-8">
          <TextField
            id="club-name"
            label="name"
            name="name"
            placeholder="what's this club called?"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={submitting}
          />

          <TextField
            id="club-description"
            label="description (optional)"
            name="description"
            placeholder="a line about the vibe"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={submitting}
          />

          <div>
            <TextField
              id="club-total-mixes"
              label="number of mystery mixes"
              name="total_mixes"
              type="number"
              min={1}
              value={totalMixes}
              onChange={(e) => setTotalMixes(e.target.value)}
              disabled={submitting}
            />
            <p className="mt-2 font-mono text-[11px] font-light text-muted">
              we&apos;ll create this many mystery mixes for you — name each one later.
            </p>
          </div>

          <TextField
            id="club-votes-per-player"
            label="votes per player"
            name="votes_per_player"
            type="number"
            min={1}
            value={votesPerPlayer}
            onChange={(e) => setVotesPerPlayer(e.target.value)}
            disabled={submitting}
          />

          <div>
            <TextField
              id="club-songs-per-submission"
              label="songs per submission"
              name="songs_per_submission"
              type="number"
              min={1}
              value={songsPerSubmission}
              onChange={(e) => setSongsPerSubmission(e.target.value)}
              disabled={submitting}
            />
            <p className="mt-2 font-mono text-[11px] font-light text-muted">
              how many songs each player can submit per mystery mix — 1 to 5.
            </p>
          </div>

          <div className="space-y-6">
            <DeadlineWindowField
              idPrefix="submission-window"
              label="submission window"
              days={submissionWindowDays}
              hours={submissionWindowHours}
              onDaysChange={setSubmissionWindowDays}
              onHoursChange={setSubmissionWindowHours}
              disabled={submitting}
            />
            <DeadlineWindowField
              idPrefix="voting-window"
              label="voting window"
              days={votingWindowDays}
              hours={votingWindowHours}
              onDaysChange={setVotingWindowDays}
              onHoursChange={setVotingWindowHours}
              disabled={submitting}
            />
            <p className="font-mono text-[11px] font-light text-muted">
              mystery mixes also close early if everyone finishes.
            </p>
          </div>

          <div>
            <label className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                name="default_vibe_mode"
                checked={defaultVibeMode}
                onChange={(e) => setDefaultVibeMode(e.target.checked)}
                disabled={submitting}
                className="h-4 w-4 rounded-[2px] border border-ink accent-sage"
              />
              <span className="font-mono uppercase tracking-ui text-[11px] text-ink">
                just vibing by default
              </span>
              <HelpLink anchor="just-vibing" />
            </label>
            <p className="mt-2 font-mono text-[11px] font-light text-muted">
              vibing means no voting or ranking — just songs and response notes. every
              member who joins starts out vibing.
            </p>
          </div>

          {guard ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {guard}
            </p>
          ) : null}

          {error ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {error}
            </p>
          ) : null}

          <div className="space-y-4">
            <Button type="submit" disabled={submitting} className="w-full">
              {submitting ? "creating…" : "create"}
            </Button>
            <div className="text-center">
              <Button variant="ghost" type="button" onClick={onCancel} disabled={submitting}>
                cancel
              </Button>
            </div>
          </div>
        </form>
      </div>
    </main>
  );
}
