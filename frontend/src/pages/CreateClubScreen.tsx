import { type FormEvent, useState } from "react";
import { Button } from "../components/Button";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { FormError } from "../components/FormError";
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

// Same caps as the backend's ClubCreate model (backend/app/api/routes/clubs.py)
// so the client never lets a value through that only the server would reject.
const MAX_NAME_LENGTH = 100;
const MAX_DESCRIPTION_LENGTH = 2000;
const MAX_MIXES = 50;

type FieldName =
  | "name"
  | "description"
  | "mixes"
  | "votes"
  | "songs"
  | "submission_window"
  | "voting_window";

// Submit order, also the order fields are focused when several are invalid at once.
const FIELD_ORDER: FieldName[] = [
  "name",
  "description",
  "mixes",
  "votes",
  "songs",
  "submission_window",
  "voting_window",
];

const FIELD_FOCUS_ID: Record<FieldName, string> = {
  name: "club-name",
  description: "club-description",
  mixes: "club-total-mixes",
  votes: "club-votes-per-player",
  songs: "club-songs-per-submission",
  submission_window: "submission-window-days",
  voting_window: "voting-window-days",
};

function validateName(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "a club needs a name.";
  if (trimmed.length > MAX_NAME_LENGTH) return `keep the name under ${MAX_NAME_LENGTH} characters.`;
  return null;
}

function validateDescription(value: string): string | null {
  if (value.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `keep the description under ${MAX_DESCRIPTION_LENGTH} characters.`;
  }
  return null;
}

function validateMixes(value: string): string | null {
  const mixes = Number(value);
  if (!Number.isInteger(mixes) || mixes < 1) return "a club needs at least one mystery mix.";
  if (mixes > MAX_MIXES) return `keep it to ${MAX_MIXES} mystery mixes or fewer.`;
  return null;
}

function validateVotes(value: string): string | null {
  const votes = Number(value);
  if (!Number.isInteger(votes) || votes < 1) return "votes per player must be at least 1.";
  return null;
}

function validateSongs(value: string): string | null {
  const songs = Number(value);
  if (!Number.isInteger(songs) || songs < 1 || songs > 5) {
    return "songs per submission must be between 1 and 5.";
  }
  return null;
}

function validateWindow(
  days: string,
  hours: string,
  label: "submission" | "voting",
): string | null {
  const totalHours = daysAndHoursToTotal(Number(days), Number(hours));
  const windowError = validateWindowHours(totalHours);
  return windowError ? `${label} ${windowError}` : null;
}

type CreateClubScreenProps = {
  onSubmit: (input: CreateClubInput) => void;
  submitting: boolean;
  error?: string | null;
  onCancel: () => void;
};

export function CreateClubScreen({ onSubmit, submitting, error, onCancel }: CreateClubScreenProps) {
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
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<FieldName, string | null>>>({});
  const [touched, setTouched] = useState<Partial<Record<FieldName, boolean>>>({});

  // Validate on blur (first pass) and live on every subsequent change once a
  // field has been touched — the one consistent trigger pattern for every
  // field on this form (MYS-239). Submit always (re)validates everything.
  function markTouchedAndValidate(field: FieldName, error: string | null) {
    setTouched((t) => ({ ...t, [field]: true }));
    setFieldErrors((prev) => ({ ...prev, [field]: error }));
  }

  function revalidateIfTouched(field: FieldName, error: string | null) {
    if (touched[field]) setFieldErrors((prev) => ({ ...prev, [field]: error }));
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const errors: Record<FieldName, string | null> = {
      name: validateName(name),
      description: validateDescription(description),
      mixes: validateMixes(totalMixes),
      votes: validateVotes(votesPerPlayer),
      songs: validateSongs(songsPerSubmission),
      submission_window: validateWindow(submissionWindowDays, submissionWindowHours, "submission"),
      voting_window: validateWindow(votingWindowDays, votingWindowHours, "voting"),
    };
    setFieldErrors(errors);
    setTouched({
      name: true,
      description: true,
      mixes: true,
      votes: true,
      songs: true,
      submission_window: true,
      voting_window: true,
    });

    const firstInvalid = FIELD_ORDER.find((field) => errors[field]);
    if (firstInvalid) {
      document.getElementById(FIELD_FOCUS_ID[firstInvalid])?.focus();
      return;
    }

    const trimmedDescription = description.trim();
    onSubmit({
      name: name.trim(),
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
      total_mixes: Number(totalMixes),
      votes_per_player: Number(votesPerPlayer),
      songs_per_submission: Number(songsPerSubmission),
      default_vibe_mode: defaultVibeMode,
      submission_window_hours: daysAndHoursToTotal(
        Number(submissionWindowDays),
        Number(submissionWindowHours),
      ),
      voting_window_hours: daysAndHoursToTotal(Number(votingWindowDays), Number(votingWindowHours)),
    });
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-8 sm:px-8">
      <div className="w-full max-w-sm">
        {/* The disc, unaccented. /clubs/new is a top-level route in App.tsx,
            outside the AuthedLayout children that mount TopNav, so this screen
            carries no nav mark and an amber hero mark here would sit inside
            ADR 0010's two-placement bound. It stays neutral anyway: the ADR
            enumerates the screens that carry the hero mark and this is not one
            of them, so accenting it would widen the identity category rather
            than apply it — the same call EmailEntryScreen made. The retired
            reason for having no accent (ADR 0004's decorative-Rust-yields-to-
            errors trade) no longer applies: form errors are `destructive-text`,
            a separate color category from amber entirely. */}
        <ConcentricRings size={72} className="mx-auto" />

        <h1 className="mt-8 text-center font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
          new club
        </h1>
        <p className="mt-2 text-center text-sm leading-[1.72] text-muted-foreground">
          anyone you invite skips the waitlist and joins straight in.
        </p>

        <form onSubmit={handleSubmit} noValidate className="mt-10 space-y-8">
          <TextField
            id="club-name"
            label="name"
            name="name"
            placeholder="what's this club called?"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              revalidateIfTouched("name", validateName(e.target.value));
            }}
            onBlur={(e) => markTouchedAndValidate("name", validateName(e.target.value))}
            disabled={submitting}
            error={fieldErrors.name}
          />

          <TextField
            id="club-description"
            label="description (optional)"
            name="description"
            placeholder="a line about the vibe"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              revalidateIfTouched("description", validateDescription(e.target.value));
            }}
            onBlur={(e) =>
              markTouchedAndValidate("description", validateDescription(e.target.value))
            }
            disabled={submitting}
            error={fieldErrors.description}
          />

          <div>
            <TextField
              id="club-total-mixes"
              label="number of mystery mixes"
              name="total_mixes"
              type="number"
              min={1}
              max={MAX_MIXES}
              value={totalMixes}
              onChange={(e) => {
                setTotalMixes(e.target.value);
                revalidateIfTouched("mixes", validateMixes(e.target.value));
              }}
              onBlur={(e) => markTouchedAndValidate("mixes", validateMixes(e.target.value))}
              disabled={submitting}
              error={fieldErrors.mixes}
            />
            <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
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
            onChange={(e) => {
              setVotesPerPlayer(e.target.value);
              revalidateIfTouched("votes", validateVotes(e.target.value));
            }}
            onBlur={(e) => markTouchedAndValidate("votes", validateVotes(e.target.value))}
            disabled={submitting}
            error={fieldErrors.votes}
          />

          <div>
            <TextField
              id="club-songs-per-submission"
              label="songs per submission"
              name="songs_per_submission"
              type="number"
              min={1}
              max={5}
              value={songsPerSubmission}
              onChange={(e) => {
                setSongsPerSubmission(e.target.value);
                revalidateIfTouched("songs", validateSongs(e.target.value));
              }}
              onBlur={(e) => markTouchedAndValidate("songs", validateSongs(e.target.value))}
              disabled={submitting}
              error={fieldErrors.songs}
            />
            <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
              how many songs each player can submit per mystery mix — 1 to 5.
            </p>
          </div>

          <div className="space-y-6">
            <DeadlineWindowField
              idPrefix="submission-window"
              label="submission window"
              days={submissionWindowDays}
              hours={submissionWindowHours}
              onDaysChange={(value) => {
                setSubmissionWindowDays(value);
                revalidateIfTouched(
                  "submission_window",
                  validateWindow(value, submissionWindowHours, "submission"),
                );
              }}
              onHoursChange={(value) => {
                setSubmissionWindowHours(value);
                revalidateIfTouched(
                  "submission_window",
                  validateWindow(submissionWindowDays, value, "submission"),
                );
              }}
              onBlur={() =>
                markTouchedAndValidate(
                  "submission_window",
                  validateWindow(submissionWindowDays, submissionWindowHours, "submission"),
                )
              }
              disabled={submitting}
              error={fieldErrors.submission_window}
            />
            <DeadlineWindowField
              idPrefix="voting-window"
              label="voting window"
              days={votingWindowDays}
              hours={votingWindowHours}
              onDaysChange={(value) => {
                setVotingWindowDays(value);
                revalidateIfTouched(
                  "voting_window",
                  validateWindow(value, votingWindowHours, "voting"),
                );
              }}
              onHoursChange={(value) => {
                setVotingWindowHours(value);
                revalidateIfTouched(
                  "voting_window",
                  validateWindow(votingWindowDays, value, "voting"),
                );
              }}
              onBlur={() =>
                markTouchedAndValidate(
                  "voting_window",
                  validateWindow(votingWindowDays, votingWindowHours, "voting"),
                )
              }
              disabled={submitting}
              error={fieldErrors.voting_window}
            />
            <p className="text-meta leading-[1.6] text-muted-foreground">
              mystery mixes also close early if everyone finishes.
            </p>
          </div>

          <div>
            <label className="flex cursor-pointer items-center gap-3">
              {/* Same drawn box as OnboardingScreen's consent checkbox: the
                  native box is removed (`appearance-none`) rather than tinted
                  with `accent-color`, because the UA paints its own checkmark
                  white and white on the amber fill is ~2.2:1, under the 3:1
                  floor for a non-text graphic. Drawing it lets the mark be
                  `accent-foreground`. Grid stacking (both children in cell 1/1)
                  puts the mark over the box without absolute positioning. */}
              <span className="grid h-4 w-4 shrink-0 place-items-center">
                <input
                  type="checkbox"
                  name="default_vibe_mode"
                  checked={defaultVibeMode}
                  onChange={(e) => setDefaultVibeMode(e.target.checked)}
                  disabled={submitting}
                  // Checked is amber because "accent for selected" is the
                  // interactive-state half of amber's action category, not
                  // decoration. The focus ring takes a `floor` offset — this
                  // screen sits on the page background — since an amber ring
                  // directly on the amber fill would be invisible. No disabled
                  // recolor: the box is only disabled while a create is in
                  // flight, the resting `muted-foreground` edge still reads at
                  // 6.38:1 there, and Tailwind orders `disabled:` after
                  // `checked:`, so one would silently drop the amber mid-submit.
                  className="peer col-start-1 row-start-1 h-4 w-4 cursor-pointer appearance-none rounded-hair border border-muted-foreground bg-transparent transition-colors duration-150 checked:border-accent checked:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-floor disabled:cursor-not-allowed"
                />
                <CheckmarkIcon className="pointer-events-none col-start-1 row-start-1 hidden text-accent-foreground peer-checked:block" />
              </span>
              {/* The control's own caption, so it takes the same mono label
                  metrics as every field label on this form but sits at
                  `foreground` rather than `muted-foreground` — it is the thing
                  being toggled, not supporting copy about it. */}
              <span className="font-mono uppercase tracking-mono-caps text-mini text-foreground">
                casual mode by default
              </span>
              <HelpLink anchor="casual-mode" />
            </label>
            <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
              casual mode means no voting or ranking, just songs and response notes. competitive
              mode means voting and a spot on the leaderboard. every member who joins starts out in
              the mode you pick here.
            </p>
          </div>

          {/* A failed create is a screen-level form error, not a field's — the
              shared `FormError` treatment (ADR 0004). Form errors are their own
              color category and consume nothing from this screen's amber, which
              is why every invalid field above may show `destructive-text` at the
              same time as this does. */}
          {error ? <FormError>{error}</FormError> : null}

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
