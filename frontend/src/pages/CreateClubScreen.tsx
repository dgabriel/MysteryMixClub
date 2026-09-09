import { type FormEvent, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PaperSurface } from "../components/PaperSurface";
import { FormError } from "../components/FormError";
import { TextField } from "../components/TextField";
import { HelpLink } from "../components/HelpLink";
import { DeadlineWindowField } from "../components/DeadlineWindowField";
import { DeadlineAnchorField, TimezoneField } from "../components/DeadlineAnchorField";
import { DeadlineModeToggle } from "../components/DeadlineModeToggle";
import { daysAndHoursToTotal, validateWindowHours } from "../utils/deadlineWindow";
import { detectTimezone, listTimezones, validateAnchor } from "../utils/deadlineAnchor";
import type { Weekday } from "../services/api";

type CreateClubInput = {
  name: string;
  description?: string;
  total_mixes: number;
  votes_per_player: number;
  songs_per_submission: number;
  default_vibe_mode: boolean;
  submission_window_hours?: number;
  voting_window_hours?: number;
  deadline_mode?: "duration" | "weekly_anchor";
  timezone?: string;
  submission_weekday?: Weekday;
  submission_time?: string;
  voting_weekday?: Weekday;
  voting_time?: string;
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
  | "voting_window"
  | "submission_anchor"
  | "voting_anchor";

// Submit order, also the order fields are focused when several are invalid at once.
const FIELD_ORDER: FieldName[] = [
  "name",
  "description",
  "mixes",
  "votes",
  "songs",
  "submission_window",
  "voting_window",
  "submission_anchor",
  "voting_anchor",
];

const FIELD_FOCUS_ID: Record<FieldName, string> = {
  name: "club-name",
  description: "club-description",
  mixes: "club-total-mixes",
  votes: "club-votes-per-player",
  songs: "club-songs-per-submission",
  submission_window: "submission-window-days",
  voting_window: "voting-window-days",
  submission_anchor: "submission-anchor-weekday",
  voting_anchor: "voting-anchor-weekday",
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
  const [submissionWindowDays, setSubmissionWindowDays] = useState(DEFAULT_WINDOW_DAYS);
  const [submissionWindowHours, setSubmissionWindowHours] = useState(DEFAULT_WINDOW_HOURS);
  const [votingWindowDays, setVotingWindowDays] = useState(DEFAULT_WINDOW_DAYS);
  const [votingWindowHours, setVotingWindowHours] = useState(DEFAULT_WINDOW_HOURS);
  // Weekly-anchor deadline mode (ADR 0021) — an alternate to the days/hours
  // window above, not a second set of fields sent alongside it.
  const [deadlineMode, setDeadlineMode] = useState<"duration" | "weekly_anchor">("duration");
  const [timezone, setTimezone] = useState(detectTimezone);
  const [submissionWeekday, setSubmissionWeekday] = useState<Weekday | "">("");
  const [submissionTime, setSubmissionTime] = useState("");
  const [votingWeekday, setVotingWeekday] = useState<Weekday | "">("");
  const [votingTime, setVotingTime] = useState("");
  const timezoneOptions = useMemo(() => listTimezones(), []);
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
    const anchorMode = deadlineMode === "weekly_anchor";
    const errors: Record<FieldName, string | null> = {
      name: validateName(name),
      description: validateDescription(description),
      mixes: validateMixes(totalMixes),
      votes: validateVotes(votesPerPlayer),
      songs: validateSongs(songsPerSubmission),
      submission_window: anchorMode
        ? null
        : validateWindow(submissionWindowDays, submissionWindowHours, "submission"),
      voting_window: anchorMode
        ? null
        : validateWindow(votingWindowDays, votingWindowHours, "voting"),
      submission_anchor: anchorMode
        ? validateAnchor(submissionWeekday, submissionTime, "submission")
        : null,
      voting_anchor: anchorMode ? validateAnchor(votingWeekday, votingTime, "voting") : null,
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
      submission_anchor: true,
      voting_anchor: true,
    });

    const firstInvalid = FIELD_ORDER.find((field) => errors[field]);
    if (firstInvalid) {
      document.getElementById(FIELD_FOCUS_ID[firstInvalid])?.focus();
      return;
    }

    const trimmedDescription = description.trim();
    const base = {
      name: name.trim(),
      ...(trimmedDescription ? { description: trimmedDescription } : {}),
      total_mixes: Number(totalMixes),
      votes_per_player: Number(votesPerPlayer),
      songs_per_submission: Number(songsPerSubmission),
      // The casual-mode toggle was pulled from this form on 2026-08-11 pending
      // a design Dawn is still working out; new clubs take the API's own
      // default until it returns. Members can still be switched
      // individually, and an organizer can change the club default later.
      default_vibe_mode: false,
    };
    if (anchorMode) {
      onSubmit({
        ...base,
        deadline_mode: "weekly_anchor",
        timezone,
        submission_weekday: submissionWeekday as Weekday,
        submission_time: submissionTime,
        voting_weekday: votingWeekday as Weekday,
        voting_time: votingTime,
      });
    } else {
      onSubmit({
        ...base,
        submission_window_hours: daysAndHoursToTotal(
          Number(submissionWindowDays),
          Number(submissionWindowHours),
        ),
        voting_window_hours: daysAndHoursToTotal(
          Number(votingWindowDays),
          Number(votingWindowHours),
        ),
      });
    }
  }

  return (
    // Light surface (ADR 0013), `nested` because this screen renders inside
    // AuthedLayout — an unnested `min-h-screen` here would push the toolbar off
    // the top of the viewport on load.
    <PaperSurface nested>
      {/* Top-aligned, not vertically centred. Centring is right for a short
          standalone screen; this form is taller than the viewport, and inside
          the nav shell `justify-center` pushed its top edge above the fold —
          the toolbar was scrolled off on load (61px, measured). */}
      <main className="flex flex-col items-center px-4 pt-8 pb-16 sm:px-8">
        <div className="w-full max-w-sm">
          {/* Left-aligned like every other screen in the nav shell. Centring
              was for the standalone version of this page, which had no
              toolbar to align to. */}
          <div className="flex items-center gap-3">
            <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
              new club
            </h1>
            {/* Beside the heading, the same place every other screen puts it —
                a lone `?` under a paragraph has nothing to be "about". */}
            <HelpLink anchor="clubs" onPaper />
          </div>
          {/* Actual help, not a tagline. Two things a first-time organizer
              cannot work out from the fields themselves: what a club *is*, and
              that votes-per-player and songs-per-submission are the only
              settings here with no edit path afterward (they are absent from
              the API's ClubUpdate — everything else on this form is in it). */}
          <div className="mt-3 space-y-3">
            <p className="text-sm leading-[1.72] text-ink-muted">
              a club is a private group running a series of mystery mixes together, one mix at a
              time, each with its own theme, songs and votes. you&apos;ll get a shareable invite
              link once it exists; anyone who uses it skips the waitlist and joins straight in.
            </p>
            <p className="text-sm leading-[1.72] text-ink-muted">
              the name, the number of mixes and the deadlines can all be changed later.{" "}
              <strong className="font-normal text-ink">
                votes per player and songs per submission can&apos;t.
              </strong>{" "}
              those are fixed for the life of the club, so set them here.
            </p>
          </div>

          <form onSubmit={handleSubmit} noValidate className="mt-10 space-y-8">
            <TextField
              onPaper
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
              onPaper
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
                onPaper
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
              <p className="mt-2 text-meta leading-[1.6] text-ink-muted">
                we&apos;ll create this many mystery mixes for you. name each one later.
              </p>
            </div>

            <TextField
              onPaper
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
                onPaper
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
              <p className="mt-2 text-meta leading-[1.6] text-ink-muted">
                how many songs each player can submit per mystery mix, from 1 to 5.
              </p>
            </div>

            <div className="space-y-6">
              <DeadlineModeToggle onPaper value={deadlineMode} onChange={setDeadlineMode} />

              {deadlineMode === "duration" ? (
                <>
                  <DeadlineWindowField
                    onPaper
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
                    onPaper
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
                  <p className="text-meta leading-[1.6] text-ink-muted">
                    mystery mixes also close early if everyone finishes.
                  </p>
                </>
              ) : (
                <>
                  <TimezoneField
                    onPaper
                    id="club-timezone"
                    value={timezone}
                    options={timezoneOptions}
                    onChange={setTimezone}
                    disabled={submitting}
                  />
                  <DeadlineAnchorField
                    onPaper
                    idPrefix="submission-anchor"
                    label="submissions due"
                    weekday={submissionWeekday}
                    time={submissionTime}
                    onWeekdayChange={(value) => {
                      setSubmissionWeekday(value);
                      revalidateIfTouched(
                        "submission_anchor",
                        validateAnchor(value, submissionTime, "submission"),
                      );
                    }}
                    onTimeChange={(value) => {
                      setSubmissionTime(value);
                      revalidateIfTouched(
                        "submission_anchor",
                        validateAnchor(submissionWeekday, value, "submission"),
                      );
                    }}
                    onBlur={() =>
                      markTouchedAndValidate(
                        "submission_anchor",
                        validateAnchor(submissionWeekday, submissionTime, "submission"),
                      )
                    }
                    disabled={submitting}
                    error={fieldErrors.submission_anchor}
                  />
                  <DeadlineAnchorField
                    onPaper
                    idPrefix="voting-anchor"
                    label="votes due"
                    weekday={votingWeekday}
                    time={votingTime}
                    onWeekdayChange={(value) => {
                      setVotingWeekday(value);
                      revalidateIfTouched(
                        "voting_anchor",
                        validateAnchor(value, votingTime, "voting"),
                      );
                    }}
                    onTimeChange={(value) => {
                      setVotingTime(value);
                      revalidateIfTouched(
                        "voting_anchor",
                        validateAnchor(votingWeekday, value, "voting"),
                      );
                    }}
                    onBlur={() =>
                      markTouchedAndValidate(
                        "voting_anchor",
                        validateAnchor(votingWeekday, votingTime, "voting"),
                      )
                    }
                    disabled={submitting}
                    error={fieldErrors.voting_anchor}
                  />
                  <p className="text-meta leading-[1.6] text-ink-muted">
                    mystery mixes also close early if everyone finishes.
                  </p>
                </>
              )}
            </div>

            {/* A failed create is a screen-level form error, not a field's — the
                shared `FormError` treatment (ADR 0004). Form errors are their own
                color category and consume nothing from this screen's amber, which
                is why every invalid field above may show `ink-destructive` at
                the same time as this does. */}
            {error ? <FormError onPaper>{error}</FormError> : null}

            <div className="space-y-4">
              <Button onPaper type="submit" disabled={submitting} className="w-full">
                {submitting ? "creating…" : "create"}
              </Button>
              <div className="text-center">
                <Button
                  onPaper
                  variant="ghost"
                  type="button"
                  onClick={onCancel}
                  disabled={submitting}
                >
                  cancel
                </Button>
              </div>
            </div>
          </form>
        </div>
      </main>
    </PaperSurface>
  );
}
