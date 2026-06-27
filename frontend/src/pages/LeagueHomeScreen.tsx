import { type FormEvent, useEffect, useState } from "react";
import type {
  LeaderboardEntry,
  League,
  LeagueMember,
  Round,
  RoundResults,
  RoundState,
} from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

const ROUND_STATE_LABEL: Record<RoundState, string> = {
  pending: "upcoming",
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "closed",
};

/** A round is "active" when members can act on it right now. */
function isActiveRound(state: RoundState): boolean {
  return state === "open_submission" || state === "open_voting";
}

type LeagueHomeScreenProps = {
  league: League;
  members: LeagueMember[];
  rounds: Round[];
  /** Reveal results keyed by round id, present once a closed round's results load. */
  roundResults: Record<string, RoundResults>;
  isOrganizer: boolean;
  loading: boolean;
  error?: string | null;
  onBack: () => void;
  onOpenRound: (roundId: string) => void;
  onUpdateRound: (
    roundId: string,
    input: { theme?: string | null; description?: string | null },
  ) => Promise<boolean>;
  savingRoundId: string | null;
  updateRoundError?: string | null;
  inviteUrl: string | null;
  onGenerateInvite: () => void;
  generatingInvite: boolean;
  inviteError?: string | null;
  onUpdateLeague: (input: {
    name?: string;
    description?: string | null;
    total_rounds?: number;
  }) => void;
  updating: boolean;
  updateError?: string | null;
  onRemoveMember: (userId: string) => void;
  removingUserId: string | null;
  removeError?: string | null;
  // --- Organizer admin: delete league (MYS-124) ---
  onDeleteLeague: () => void;
  deletingLeague: boolean;
  deleteLeagueError?: string | null;
};

export function LeagueHomeScreen({
  league,
  members,
  rounds,
  roundResults,
  isOrganizer,
  loading,
  error,
  onBack,
  onOpenRound,
  onUpdateRound,
  savingRoundId,
  updateRoundError,
  inviteUrl,
  onGenerateInvite,
  generatingInvite,
  inviteError,
  onUpdateLeague,
  updating,
  updateError,
  onRemoveMember,
  removingUserId,
  removeError,
  onDeleteLeague,
  deletingLeague,
  deleteLeagueError,
}: LeagueHomeScreenProps) {
  if (loading) {
    return (
      <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-4 text-center sm:px-8">
        <p className="font-mono text-[13px] font-light text-muted">{error}</p>
        <div className="mt-6">
          <Button variant="ghost" type="button" onClick={onBack}>
            back
          </Button>
        </div>
      </main>
    );
  }

  // Rust budget: this screen's single Rust signal is reserved for the organizer's
  // destructive delete-league confirm (DeleteLeagueSection below). Every other
  // element — including the league-state badge — stays in the Sage family. The
  // shared TopNav is rendered by AuthedLayout, so this is content-only.
  return (
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      <div className="flex items-start justify-between gap-4">
        <h1 className="font-serif text-[32px] leading-tight text-ink">{league.name}</h1>
        <div className="shrink-0 pt-2">
          <Badge>{league.state}</Badge>
        </div>
      </div>
        {league.description ? (
          <p className="mt-2 font-mono text-[13px] font-light text-muted">{league.description}</p>
        ) : null}
        <p className="mt-3 font-mono text-[11px] font-light text-muted">
          round {league.current_round} of {league.total_rounds}
        </p>

        {isOrganizer ? (
          <OrganizerEdit
            league={league}
            onUpdateLeague={onUpdateLeague}
            updating={updating}
            updateError={updateError}
          />
        ) : null}

        {/* Rounds */}
        <RoundsSection
          rounds={rounds}
          roundResults={roundResults}
          isOrganizer={isOrganizer}
          onOpenRound={onOpenRound}
          onUpdateRound={onUpdateRound}
          savingRoundId={savingRoundId}
          updateRoundError={updateRoundError}
        />

        {/* Members */}
        <section className="mt-12">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
            members ({members.length})
          </h2>
          <ul className="mt-4 divide-y divide-border border-t border-border">
            {members.map((member) => {
              const showRemove = isOrganizer && !member.is_organizer;
              return (
                <li key={member.user_id} className="flex items-center justify-between gap-4 py-3">
                  <span className="flex items-center gap-3">
                    <span className="font-mono text-[13px] text-ink">{member.display_name}</span>
                    {member.is_organizer ? <Badge>organizer</Badge> : null}
                  </span>
                  {showRemove ? (
                    <button
                      type="button"
                      onClick={() => onRemoveMember(member.user_id)}
                      disabled={removingUserId === member.user_id}
                      className="font-mono uppercase tracking-ui text-[11px] text-ink underline underline-offset-[3px] hover:text-sage disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {removingUserId === member.user_id ? "removing…" : "remove"}
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {removeError ? (
            <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
              {removeError}
            </p>
          ) : null}
        </section>

        {/* Invite share — a single shareable link, visible to any member. The
            link expires after 48h; calm copy says so. */}
        <section className="mt-12">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">invite</h2>
          <div className="mt-4">
            {inviteUrl ? (
              <InviteShare inviteUrl={inviteUrl} />
            ) : (
              <>
                <Button type="button" onClick={onGenerateInvite} disabled={generatingInvite}>
                  {generatingInvite ? "generating…" : "invite"}
                </Button>
                <p className="mt-3 font-mono text-[11px] font-light text-muted">
                  a shareable link, good for 48 hours.
                </p>
              </>
            )}
          </div>
          {inviteError ? (
            <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
              {inviteError}
            </p>
          ) : null}
        </section>

        {/* Organizer-only destructive action. */}
        {isOrganizer ? (
          <DeleteLeagueSection
            onDeleteLeague={onDeleteLeague}
            deletingLeague={deletingLeague}
            deleteLeagueError={deleteLeagueError}
          />
        ) : null}
    </main>
  );
}

/**
 * Organizer-only destructive action. A two-step confirm (calm copy, no
 * exclamation marks): the first action arms the confirm, the second commits.
 * This confirm carries the screen's single Rust signal — the `link`-variant
 * Button renders in Rust. The backend rejects deleting an in-progress league
 * (409); that calm message is surfaced verbatim.
 */
function DeleteLeagueSection({
  onDeleteLeague,
  deletingLeague,
  deleteLeagueError,
}: {
  onDeleteLeague: () => void;
  deletingLeague: boolean;
  deleteLeagueError?: string | null;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <section className="mt-12 border-t border-border pt-6">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">delete league</h2>

      {confirming ? (
        <div className="mt-4 space-y-4">
          <p className="font-mono text-[13px] font-light text-muted">
            this removes the league and everything in it. it can't be undone.
          </p>
          <div className="flex items-center gap-4">
            {/* The screen's single Rust use: the destructive confirm. */}
            <Button
              variant="link"
              type="button"
              onClick={onDeleteLeague}
              disabled={deletingLeague}
            >
              {deletingLeague ? "deleting…" : "delete this league"}
            </Button>
            <Button
              variant="ghost"
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deletingLeague}
            >
              cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4">
          <Button variant="ghost" type="button" onClick={() => setConfirming(true)}>
            delete league
          </Button>
        </div>
      )}

      {deleteLeagueError ? (
        <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
          {deleteLeagueError}
        </p>
      ) : null}
    </section>
  );
}

function RoundsSection({
  rounds,
  roundResults,
  isOrganizer,
  onOpenRound,
  onUpdateRound,
  savingRoundId,
  updateRoundError,
}: {
  rounds: Round[];
  roundResults: Record<string, RoundResults>;
  isOrganizer: boolean;
  onOpenRound: (roundId: string) => void;
  onUpdateRound: (
    roundId: string,
    input: { theme?: string | null; description?: string | null },
  ) => Promise<boolean>;
  savingRoundId: string | null;
  updateRoundError?: string | null;
}) {
  // Rounds are auto-created with the league, so the slate always exists. The
  // empty state is a fallback only (e.g. a stale/odd league with zero rounds).
  return (
    <section className="mt-12">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        rounds ({rounds.length})
      </h2>

      {rounds.length === 0 ? (
        <p className="mt-4 font-mono text-[13px] font-light text-muted">no rounds yet</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {rounds.map((round) => (
            <li key={round.id}>
              <RoundRow
                round={round}
                results={roundResults[round.id]}
                isOrganizer={isOrganizer}
                onOpen={() => onOpenRound(round.id)}
                onUpdate={(input) => onUpdateRound(round.id, input)}
                saving={savingRoundId === round.id}
                error={savingRoundId === round.id ? updateRoundError : null}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One round in the rounds list. State drives the visual weight, within the
 * Sage/Ink family only — no Rust here (the screen reserves its single Rust use
 * for the delete-league confirm):
 *  - active round (open submission/voting) → Sage-pale fill, the eye lands here
 *  - upcoming (pending) → muted theme, quiet
 *  - closed → plain
 *
 * The heading is always "round N". When the organizer has named the round the
 * theme shows beneath it; an unnamed round shows a quiet muted prompt to the
 * organizer (and nothing to members). Organizers can rename a `pending` round
 * in place (theme + description); once it opens the API locks those fields
 * (409), so the edit affordance is replaced by a calm muted note.
 *
 * A closed round also carries a compact reveal summary — the winner (top of the
 * vote leaderboard) and the most-noted pick — once its `results` have loaded.
 * Ties show every co-winner.
 */
function RoundRow({
  round,
  results,
  isOrganizer,
  onOpen,
  onUpdate,
  saving,
  error,
}: {
  round: Round;
  results?: RoundResults;
  isOrganizer: boolean;
  onOpen: () => void;
  onUpdate: (input: { theme?: string | null; description?: string | null }) => Promise<boolean>;
  saving: boolean;
  error?: string | null;
}) {
  const [editing, setEditing] = useState(false);

  const active = isActiveRound(round.state);
  const pending = round.state === "pending";
  const named = !!round.theme;

  if (editing) {
    return (
      <div className="rounded-[3px] border border-border bg-white px-5 py-5">
        <RoundEditForm
          round={round}
          saving={saving}
          error={error}
          onCancel={() => setEditing(false)}
          onSave={async (input) => {
            const ok = await onUpdate(input);
            if (ok) setEditing(false);
          }}
        />
      </div>
    );
  }

  return (
    <div
      className={[
        "rounded-[3px] border px-5 py-4 transition-colors duration-150",
        active ? "border-sage bg-sage-pale" : "border-border bg-white",
      ].join(" ")}
    >
      <button type="button" onClick={onOpen} className="block w-full text-left">
        <div className="flex items-start justify-between gap-4">
          <span className="min-w-0">
            <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
              round {round.round_number}
            </span>
            {named ? (
              <span className="mt-0.5 block truncate font-serif text-[16px] text-ink">
                {round.theme}
              </span>
            ) : isOrganizer ? (
              <span className="mt-0.5 block truncate font-mono text-[13px] font-light italic text-muted">
                untitled — add a theme
              </span>
            ) : null}
          </span>
          <span className="shrink-0">
            <Badge>{ROUND_STATE_LABEL[round.state]}</Badge>
          </span>
        </div>
        {round.description ? (
          <p className="mt-2 font-mono text-[11px] font-light leading-relaxed text-muted">
            {round.description}
          </p>
        ) : null}
        {/* Submission progress while the round is open for submissions (MYS-101). */}
        {round.state === "open_submission" && round.member_count > 0 ? (
          <p className="mt-2 font-mono uppercase tracking-label text-[9px] text-muted">
            {round.submission_count} of {round.member_count} submitted
          </p>
        ) : null}
        {/* Viewer participation indicators — subtle sage checkmarks. */}
        {round.viewer_submitted || round.viewer_voted ? (
          <p className="mt-1.5 flex items-center gap-3 font-mono uppercase tracking-label text-[9px] text-sage">
            {round.viewer_submitted ? <ViewerCheck label="you submitted" /> : null}
            {round.viewer_voted ? <ViewerCheck label="you voted" /> : null}
          </p>
        ) : null}
        {round.state === "closed" && results ? <ClosedRoundSummary results={results} /> : null}
      </button>

      {isOrganizer ? (
        <div className="mt-3">
          {pending ? (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
            >
              {named ? "edit" : "add a theme"}
            </button>
          ) : (
            <p className="font-mono text-[11px] font-light text-muted">
              theme locks once a round opens
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** Small checkmark with a visible label — sage-coloured, screened from AT so
 *  only the label text is announced. */
function ViewerCheck({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <svg
        width="9"
        height="9"
        viewBox="0 0 12 12"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <polyline points="1.5 6.5 4.5 9.5 10.5 2.5" />
      </svg>
      {label}
    </span>
  );
}

/**
 * The leaderboard ranks playing submitters by votes with *sequential* ranks, so
 * a tie for first is not a shared rank — detect it by matching the top
 * vote_count. A top score of zero means nobody was voted for: no winner.
 */
function topVoteWinners(leaderboard: LeaderboardEntry[]): LeaderboardEntry[] {
  const top = leaderboard[0]?.vote_count ?? 0;
  if (top <= 0) return [];
  return leaderboard.filter((entry) => entry.vote_count === top);
}

/**
 * Compact reveal summary for a closed round's card: the winner (top of the vote
 * leaderboard) and the most-noted pick. Both can tie — every co-winner is named.
 * Label-left / value-right, staying in the Sage/Ink family (no Rust here — the
 * screen reserves its single Rust use for the delete-league confirm).
 */
function ClosedRoundSummary({ results }: { results: RoundResults }) {
  const winners = topVoteWinners(results.leaderboard);
  const mostNoted = results.most_noted.winners;
  if (winners.length === 0 && mostNoted.length === 0) return null;

  return (
    <dl className="mt-3 space-y-2 border-t border-border pt-3">
      {winners.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="shrink-0 font-mono uppercase tracking-label text-[9px] text-muted">
            {winners.length > 1 ? "winners" : "winner"}
          </dt>
          <dd className="min-w-0 text-right font-mono text-[13px] font-light text-ink">
            {winners.map((w) => w.display_name).join(" & ")}
          </dd>
        </div>
      ) : null}
      {mostNoted.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="shrink-0 font-mono uppercase tracking-label text-[9px] text-muted">
            most noted
          </dt>
          <dd className="min-w-0 text-right font-mono text-[13px] font-light text-ink">
            {mostNoted.map((w) => w.title).join(" · ")}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

/**
 * Inline theme + description editor for a single pending round, shown in place
 * within the rounds list. Underline inputs only (TextField + an underline
 * textarea), matching the round-detail editor. No Rust — this screen's single
 * Rust use is the delete-league confirm.
 */
function RoundEditForm({
  round,
  saving,
  error,
  onCancel,
  onSave,
}: {
  round: Round;
  saving: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (input: { theme?: string | null; description?: string | null }) => void;
}) {
  const [theme, setTheme] = useState(round.theme ?? "");
  const [description, setDescription] = useState(round.description ?? "");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const input: { theme?: string | null; description?: string | null } = {};

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
      onCancel();
      return;
    }
    onSave(input);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
        round {round.round_number}
      </span>

      <TextField
        id={`round-theme-${round.id}`}
        label="theme"
        name="theme"
        placeholder="late summer feels"
        value={theme}
        onChange={(e) => setTheme(e.target.value)}
        disabled={saving}
        autoComplete="off"
      />

      <label htmlFor={`round-description-${round.id}`} className="block">
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          description
        </span>
        <textarea
          id={`round-description-${round.id}`}
          rows={2}
          placeholder="a line or two of color for this round"
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
        <Button variant="ghost" type="button" onClick={onCancel} disabled={saving}>
          cancel
        </Button>
      </div>
    </form>
  );
}

function OrganizerEdit({
  league,
  onUpdateLeague,
  updating,
  updateError,
}: {
  league: League;
  onUpdateLeague: LeagueHomeScreenProps["onUpdateLeague"];
  updating: boolean;
  updateError?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(league.name);
  const [description, setDescription] = useState(league.description ?? "");
  const [totalRounds, setTotalRounds] = useState(String(league.total_rounds));

  function openForm() {
    setName(league.name);
    setDescription(league.description ?? "");
    setTotalRounds(String(league.total_rounds));
    setOpen(true);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const input: { name?: string; description?: string | null; total_rounds?: number } = {};

    const trimmedName = name.trim();
    if (trimmedName && trimmedName !== league.name) input.name = trimmedName;

    const trimmedDescription = description.trim();
    const currentDescription = league.description ?? "";
    if (trimmedDescription !== currentDescription) {
      input.description = trimmedDescription ? trimmedDescription : null;
    }

    const rounds = Number(totalRounds);
    if (Number.isFinite(rounds) && rounds >= 1 && rounds !== league.total_rounds) {
      input.total_rounds = rounds;
    }

    onUpdateLeague(input);
  }

  if (!open) {
    return (
      <div className="mt-6">
        <Button variant="ghost" type="button" onClick={openForm}>
          edit
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6 space-y-6 border-t border-border pt-6">
      <TextField
        id="edit-league-name"
        label="name"
        name="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={updating}
      />
      <TextField
        id="edit-league-description"
        label="description"
        name="description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={updating}
      />
      <TextField
        id="edit-league-total-rounds"
        label="rounds"
        name="total_rounds"
        type="number"
        min={1}
        value={totalRounds}
        onChange={(e) => setTotalRounds(e.target.value)}
        disabled={updating}
      />
      {updateError ? (
        <p role="alert" className="font-mono text-[11px] text-ink">
          {updateError}
        </p>
      ) : null}
      <div className="flex items-center gap-4">
        <Button type="submit" disabled={updating}>
          {updating ? "saving…" : "save"}
        </Button>
        <Button variant="ghost" type="button" onClick={() => setOpen(false)} disabled={updating}>
          cancel
        </Button>
      </div>
    </form>
  );
}

function InviteShare({ inviteUrl }: { inviteUrl: string }) {
  const [copied, setCopied] = useState(false);
  const canShare = typeof navigator !== "undefined" && typeof navigator.share === "function";

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
    } catch {
      // clipboard unavailable — leave the field for manual copy.
    }
  }

  async function handleShare() {
    try {
      await navigator.share({ url: inviteUrl });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      // any other share failure is non-fatal — the url remains visible.
    }
  }

  return (
    <div>
      <label htmlFor="invite-url" className="block">
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          share link
        </span>
        <input
          id="invite-url"
          readOnly
          value={inviteUrl}
          onFocus={(e) => e.currentTarget.select()}
          className="mt-2 w-full bg-transparent font-mono text-[13px] text-ink border-0 border-b border-ink rounded-none px-0 py-1 focus:outline-none focus:border-sage"
        />
      </label>
      <p className="mt-3 font-mono text-[11px] font-light text-muted">
        this link expires in 48 hours.
      </p>
      <div className="mt-4 flex items-center gap-4">
        <Button type="button" onClick={handleCopy}>
          {copied ? "copied" : "copy"}
        </Button>
        {canShare ? (
          <Button variant="ghost" type="button" onClick={handleShare}>
            share
          </Button>
        ) : null}
      </div>
    </div>
  );
}
