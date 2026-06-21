import { type FormEvent, useEffect, useState } from "react";
import type { League, LeagueMember, Round, RoundBatchItem, RoundState } from "../services/api";
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
  isOrganizer: boolean;
  loading: boolean;
  error?: string | null;
  onBack: () => void;
  onOpenRound: (roundId: string) => void;
  onCreateRounds: (rounds: RoundBatchItem[]) => void;
  creatingRounds: boolean;
  createRoundsError?: string | null;
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
};

export function LeagueHomeScreen({
  league,
  members,
  rounds,
  isOrganizer,
  loading,
  error,
  onBack,
  onOpenRound,
  onCreateRounds,
  creatingRounds,
  createRoundsError,
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
}: LeagueHomeScreenProps) {
  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center px-4 text-center sm:px-8">
        <p className="font-mono text-[13px] font-light text-muted">{error}</p>
        <div className="mt-6">
          <Button variant="ghost" type="button" onClick={onBack}>
            back
          </Button>
        </div>
      </main>
    );
  }

  // The screen's one Rust use: the state Badge turns Rust only when the league is
  // complete. Every other element on this screen stays in the Sage family.
  const stateIsComplete = league.state === "complete";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="px-4 py-4 sm:px-8">
        <Button variant="ghost" type="button" onClick={onBack}>
          back
        </Button>
      </header>

      <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
        <div className="flex items-start justify-between gap-4">
          <h1 className="font-serif text-[32px] leading-tight text-ink">{league.name}</h1>
          <div className="shrink-0 pt-2">
            <Badge variant={stateIsComplete ? "accent" : "default"}>{league.state}</Badge>
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
          isOrganizer={isOrganizer}
          canCreate={league.state !== "complete"}
          onOpenRound={onOpenRound}
          onCreateRounds={onCreateRounds}
          creatingRounds={creatingRounds}
          createRoundsError={createRoundsError}
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

        {/* Invite share — visible to any member */}
        <section className="mt-12">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">invite</h2>
          <div className="mt-4">
            {inviteUrl ? (
              <InviteShare inviteUrl={inviteUrl} />
            ) : (
              <Button type="button" onClick={onGenerateInvite} disabled={generatingInvite}>
                {generatingInvite ? "generating…" : "invite"}
              </Button>
            )}
          </div>
          {inviteError ? (
            <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
              {inviteError}
            </p>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function RoundsSection({
  rounds,
  isOrganizer,
  canCreate,
  onOpenRound,
  onCreateRounds,
  creatingRounds,
  createRoundsError,
}: {
  rounds: Round[];
  isOrganizer: boolean;
  canCreate: boolean;
  onOpenRound: (roundId: string) => void;
  onCreateRounds: (rounds: RoundBatchItem[]) => void;
  creatingRounds: boolean;
  createRoundsError?: string | null;
}) {
  // The batch pre-create form is only available before any rounds exist — the
  // backend guards POST :batch the same way (409 once a league has rounds).
  const canBulkCreate = isOrganizer && canCreate && rounds.length === 0;

  return (
    <section className="mt-12">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        rounds ({rounds.length})
      </h2>

      {rounds.length === 0 ? (
        canBulkCreate ? null : (
          <p className="mt-4 font-mono text-[13px] font-light text-muted">no rounds yet</p>
        )
      ) : (
        <ul className="mt-4 space-y-3">
          {rounds.map((round) => (
            <li key={round.id}>
              <RoundRow round={round} onOpen={() => onOpenRound(round.id)} />
            </li>
          ))}
        </ul>
      )}

      {canBulkCreate ? (
        <BulkCreateRounds
          onCreateRounds={onCreateRounds}
          creating={creatingRounds}
          error={createRoundsError}
        />
      ) : null}
    </section>
  );
}

/**
 * One round in the "upcoming rounds" list. State drives the visual weight,
 * within the Sage/Ink family only — no Rust here (the screen reserves its single
 * Rust use for the league-complete badge above):
 *  - active round (open submission/voting) → Sage-pale fill, the eye lands here
 *  - upcoming (pending) → muted theme, quiet
 *  - closed → plain
 * Theme + description (the organizer's color) are shown for every state.
 */
function RoundRow({ round, onOpen }: { round: Round; onOpen: () => void }) {
  const active = isActiveRound(round.state);
  const pending = round.state === "pending";

  return (
    <button
      type="button"
      onClick={onOpen}
      className={[
        "block w-full rounded-[3px] border px-5 py-4 text-left transition-colors duration-150",
        active
          ? "border-sage bg-sage-pale"
          : "border-border bg-white hover:bg-sage-pale/60",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-4">
        <span className="min-w-0">
          <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
            round {round.round_number}
          </span>
          <span
            className={[
              "mt-0.5 block truncate font-serif text-[16px]",
              pending ? "text-muted" : "text-ink",
            ].join(" ")}
          >
            {round.theme}
          </span>
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
    </button>
  );
}

/** A single editable row in the bulk pre-create form (client-side only). */
type DraftRound = {
  theme: string;
  description: string;
  submissionDeadline: string;
  votingDeadline: string;
};

function emptyDraft(): DraftRound {
  return { theme: "", description: "", submissionDeadline: "", votingDeadline: "" };
}

/** Convert a datetime-local value ("2026-07-01T18:00") to an ISO string, or null
 *  when blank. The browser supplies local time; new Date(...).toISOString()
 *  normalizes it to UTC for the API. */
function toIsoOrNull(local: string): string | null {
  if (!local.trim()) return null;
  const parsed = new Date(local);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/**
 * Organizer-only bulk pre-create form. A dynamic list of round rows — add or
 * remove a row — each with a required theme, an optional multi-line description
 * (the organizer's space to add color), and optional submission/voting
 * deadlines. Submits every non-empty row to POST :batch in one call.
 *
 * Style notes: inputs are underline-only (TextField + an underline textarea).
 * Each row is a plain bordered card; no Rust — this screen's single Rust use is
 * the league-complete badge. Add/remove are tertiary text actions in Sage.
 */
function BulkCreateRounds({
  onCreateRounds,
  creating,
  error,
}: {
  onCreateRounds: (rounds: RoundBatchItem[]) => void;
  creating: boolean;
  error?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<DraftRound[]>([emptyDraft()]);

  function update(index: number, patch: Partial<DraftRound>) {
    setDrafts((current) => current.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function addRow() {
    setDrafts((current) => [...current, emptyDraft()]);
  }

  function removeRow(index: number) {
    setDrafts((current) => current.filter((_, i) => i !== index));
  }

  const filled = drafts.filter((d) => d.theme.trim());

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (filled.length === 0) return;
    const payload: RoundBatchItem[] = filled.map((d) => {
      const item: RoundBatchItem = { theme: d.theme.trim() };
      const description = d.description.trim();
      if (description) item.description = description;
      const submission = toIsoOrNull(d.submissionDeadline);
      if (submission) item.submission_deadline = submission;
      const voting = toIsoOrNull(d.votingDeadline);
      if (voting) item.voting_deadline = voting;
      return item;
    });
    onCreateRounds(payload);
  }

  if (!open) {
    return (
      <div className="mt-4">
        <Button variant="ghost" type="button" onClick={() => setOpen(true)}>
          plan rounds
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mt-6 space-y-6 border-t border-border pt-6">
      <p className="font-mono text-[13px] font-light text-muted">
        set up every round at once. you can fine-tune each one later, while it&apos;s still
        upcoming.
      </p>

      <ol className="space-y-6">
        {drafts.map((draft, index) => (
          <li key={index} className="rounded-[3px] border border-border bg-white px-5 py-5">
            <div className="flex items-center justify-between gap-4">
              <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                round {index + 1}
              </span>
              {drafts.length > 1 ? (
                <button
                  type="button"
                  onClick={() => removeRow(index)}
                  disabled={creating}
                  className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
                >
                  remove
                </button>
              ) : null}
            </div>

            <div className="mt-4 space-y-5">
              <TextField
                id={`round-theme-${index}`}
                label="theme"
                name={`theme-${index}`}
                placeholder="late summer feels"
                value={draft.theme}
                onChange={(e) => update(index, { theme: e.target.value })}
                disabled={creating}
                autoComplete="off"
              />

              <label htmlFor={`round-description-${index}`} className="block">
                <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
                  description
                </span>
                <textarea
                  id={`round-description-${index}`}
                  rows={2}
                  placeholder="a line or two of color for this round"
                  value={draft.description}
                  onChange={(e) => update(index, { description: e.target.value })}
                  disabled={creating}
                  className="mt-2 w-full resize-none rounded-none border-0 border-b border-ink bg-transparent px-0 py-1 font-mono text-[13px] font-light text-ink placeholder:text-muted focus:border-sage focus:outline-none disabled:opacity-50"
                />
              </label>

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <TextField
                  id={`round-submission-${index}`}
                  label="submissions close"
                  name={`submission-${index}`}
                  type="datetime-local"
                  value={draft.submissionDeadline}
                  onChange={(e) => update(index, { submissionDeadline: e.target.value })}
                  disabled={creating}
                />
                <TextField
                  id={`round-voting-${index}`}
                  label="voting closes"
                  name={`voting-${index}`}
                  type="datetime-local"
                  value={draft.votingDeadline}
                  onChange={(e) => update(index, { votingDeadline: e.target.value })}
                  disabled={creating}
                />
              </div>
            </div>
          </li>
        ))}
      </ol>

      <button
        type="button"
        onClick={addRow}
        disabled={creating}
        className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
      >
        add a round
      </button>

      {error ? (
        <p role="alert" className="font-mono text-[11px] text-ink">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-4">
        <Button type="submit" disabled={creating || filled.length === 0}>
          {creating
            ? "creating…"
            : `create ${filled.length || ""} ${filled.length === 1 ? "round" : "rounds"}`.trim()}
        </Button>
        <Button
          variant="ghost"
          type="button"
          onClick={() => setOpen(false)}
          disabled={creating}
        >
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
