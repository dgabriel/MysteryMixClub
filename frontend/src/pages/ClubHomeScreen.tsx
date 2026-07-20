import { type FormEvent, useState } from "react";
import type {
  LeaderboardEntry,
  Club,
  ClubMember,
  Mix,
  MixResults,
  MixState,
} from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { CrownIcon } from "../components/CrownIcon";
import { Confetti } from "../components/Confetti";
import { DeadlineChip } from "../components/DeadlineChip";
import { DeadlineWindowField } from "../components/DeadlineWindowField";
import { InviteShare } from "../components/InviteShare";
import {
  daysAndHoursToTotal,
  hoursToDaysAndHours,
  validateWindowHours,
} from "../utils/deadlineWindow";

const MIX_STATE_LABEL: Record<MixState, string> = {
  pending: "upcoming",
  open_submission: "submissions open",
  open_voting: "voting open",
  closed: "closed",
};

/** A mix is "active" when members can act on it right now. */
function isActiveMix(state: MixState): boolean {
  return state === "open_submission" || state === "open_voting";
}

type ClubHomeScreenProps = {
  club: Club;
  members: ClubMember[];
  mixes: Mix[];
  /** Reveal results keyed by mix id, present once a closed mix's results load. */
  mixResults: Record<string, MixResults>;
  /** The fixed organizer only — narrower than isAdmin. Still needed to decide
   *  whether the leave-club section renders (co-organizers can leave; the
   *  fixed organizer cannot). */
  isOrganizer: boolean;
  /** isOrganizer OR the caller's own membership row has is_admin === true
   *  (co-organizer, MYS-99). Gates mix management, club settings edit,
   *  and member removal/role changes. */
  isAdmin: boolean;
  loading: boolean;
  error?: string | null;
  onBack: () => void;
  onOpenMix: (mixId: string) => void;
  onUpdateMix: (
    mixId: string,
    input: { theme?: string | null; description?: string | null },
  ) => Promise<boolean>;
  savingMixId: string | null;
  updateMixError?: string | null;
  inviteUrl: string | null;
  onGenerateInvite: () => void;
  generatingInvite: boolean;
  inviteError?: string | null;
  onUpdateClub: (input: {
    name?: string;
    description?: string | null;
    total_mixes?: number;
    submission_window_hours?: number;
    voting_window_hours?: number;
  }) => void;
  updating: boolean;
  updateError?: string | null;
  onRemoveMember: (userId: string) => void;
  removingUserId: string | null;
  removeError?: string | null;
  // --- Co-organizer promote/demote (MYS-99) ---
  onChangeMemberRole: (userId: string, role: "admin" | "member") => void;
  changingRoleUserId: string | null;
  roleChangeError?: string | null;
  // --- Organizer admin: delete club (MYS-124) ---
  onDeleteClub: () => void;
  deletingClub: boolean;
  deleteClubError?: string | null;
  // --- Member self-leave (MYS-97) ---
  onLeaveClub: () => void;
  leavingClub: boolean;
  leaveClubError?: string | null;
  // --- All-time vote leaderboard (MYS-157) ---
  leaderboard: LeaderboardEntry[];
  userId: string | null;
};

export function ClubHomeScreen({
  club,
  members,
  mixes,
  mixResults,
  isOrganizer,
  isAdmin,
  loading,
  error,
  onBack,
  onOpenMix,
  onUpdateMix,
  savingMixId,
  updateMixError,
  inviteUrl,
  onGenerateInvite,
  generatingInvite,
  inviteError,
  onUpdateClub,
  updating,
  updateError,
  onRemoveMember,
  removingUserId,
  removeError,
  onChangeMemberRole,
  changingRoleUserId,
  roleChangeError,
  onDeleteClub,
  deletingClub,
  deleteClubError,
  onLeaveClub,
  leavingClub,
  leaveClubError,
  leaderboard,
  userId,
}: ClubHomeScreenProps) {
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

  // Rust budget: this screen's single Rust signal is reserved for the
  // destructive delete-club confirm (DeleteClubSection below), visible to
  // any admin — the fixed organizer or a co-organizer (MYS-99). Every other
  // element — including the club-state badge and the co-organizer badge —
  // stays in the Sage family. The shared TopNav is rendered by AuthedLayout,
  // so this is content-only.
  const isComplete = club.state === "complete";

  return (
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      {isComplete ? <Confetti /> : null}
      <div className="flex items-start justify-between gap-4">
        <h1 className="font-serif text-[32px] leading-tight text-ink">{club.name}</h1>
        <div className="shrink-0 pt-2">
          <Badge>{club.state}</Badge>
        </div>
      </div>
        {club.description ? (
          <p className="mt-2 font-mono text-[13px] font-light text-muted">{club.description}</p>
        ) : null}
        <p className="mt-3 font-mono text-[11px] font-light text-muted">
          mix {club.current_mix} of {club.total_mixes}
        </p>
        {isComplete ? (
          <p className="mt-4 font-serif italic text-[18px] text-muted">
            this club has wrapped.
          </p>
        ) : null}

        {isAdmin ? (
          <OrganizerEdit
            club={club}
            onUpdateClub={onUpdateClub}
            updating={updating}
            updateError={updateError}
          />
        ) : null}

        {/* Mixes */}
        <MixesSection
          mixes={mixes}
          mixResults={mixResults}
          isAdmin={isAdmin}
          onOpenMix={onOpenMix}
          onUpdateMix={onUpdateMix}
          savingMixId={savingMixId}
          updateMixError={updateMixError}
        />

        {/* Members / all-time leaderboard (MYS-157) */}
        <section className="mt-12">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
            members ({members.length})
          </h2>
          <ul className="mt-4 divide-y divide-border border-t border-border">
            {leaderboard.map((entry) => {
              const member = members.find((m) => m.user_id === entry.user_id);
              const isMe = entry.user_id === userId;
              // The fixed organizer's role can't be toggled or removed by anyone
              // (MYS-99) — every other member, including other co-organizers, is
              // fair game for any current admin.
              const showRoleAndRemove = isAdmin && member && !member.is_organizer;
              const anyVotes = leaderboard.some((e) => e.vote_count > 0);
              return (
                <li
                  key={entry.user_id}
                  className="flex items-center justify-between gap-4 py-3"
                >
                  <span className="flex items-center gap-3">
                    <span className="w-6 shrink-0 font-mono text-[11px] text-muted">
                      {anyVotes
                        ? entry.rank === 1
                          ? <CrownIcon className="h-3.5 w-3.5 text-muted" />
                          : `#${entry.rank}`
                        : null}
                    </span>
                    <span
                      className={`font-mono text-[13px] ${isMe ? "font-semibold text-sage" : "text-ink"}`}
                    >
                      {entry.display_name}
                    </span>
                    {member?.is_organizer ? <Badge>organizer</Badge> : null}
                    {member?.is_admin && !member?.is_organizer ? (
                      <Badge>co-organizer</Badge>
                    ) : null}
                  </span>
                  <span className="flex items-center gap-4">
                    <span className="font-mono text-[11px] text-muted">
                      {entry.vote_count} {entry.vote_count === 1 ? "vote" : "votes"}
                    </span>
                    {showRoleAndRemove ? (
                      <button
                        type="button"
                        onClick={() =>
                          onChangeMemberRole(entry.user_id, member.is_admin ? "member" : "admin")
                        }
                        disabled={changingRoleUserId === entry.user_id}
                        className="font-mono uppercase tracking-ui text-[11px] text-ink underline underline-offset-[3px] hover:text-sage disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {changingRoleUserId === entry.user_id
                          ? "saving…"
                          : member.is_admin
                            ? "remove admin"
                            : "make admin"}
                      </button>
                    ) : null}
                    {showRoleAndRemove ? (
                      <button
                        type="button"
                        onClick={() => onRemoveMember(entry.user_id)}
                        disabled={removingUserId === entry.user_id}
                        className="font-mono uppercase tracking-ui text-[11px] text-ink underline underline-offset-[3px] hover:text-sage disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {removingUserId === entry.user_id ? "removing…" : "remove"}
                      </button>
                    ) : null}
                  </span>
                </li>
              );
            })}
          </ul>
          {roleChangeError ? (
            <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
              {roleChangeError}
            </p>
          ) : null}
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

        {/* Destructive actions (MYS-99): any admin (fixed organizer or
            co-organizer) can delete the club outright. The fixed organizer
            can never leave (the backend guard blocks it) so they only see
            delete; a co-organizer is the one case that sees both — they can
            leave individually, or delete the whole club; a plain member
            only sees leave. Delete's confirm carries this screen's single
            Rust signal (see DeleteClubSection) — because a co-organizer can
            have both sections open at once, LeaveClubSection's confirm
            intentionally stays in the Sage/ghost family, never Rust. */}
        {isAdmin ? (
          <DeleteClubSection
            onDeleteClub={onDeleteClub}
            deletingClub={deletingClub}
            deleteClubError={deleteClubError}
          />
        ) : null}
        {!isOrganizer ? (
          <LeaveClubSection
            onLeaveClub={onLeaveClub}
            leavingClub={leavingClub}
            leaveClubError={leaveClubError}
          />
        ) : null}
    </main>
  );
}

/**
 * Admin-only destructive action — the fixed organizer or any co-organizer
 * (MYS-99). A two-step confirm (calm copy, no exclamation marks): the first
 * action arms the confirm, the second commits. This confirm carries the
 * screen's single Rust signal — the `link`-variant Button renders in Rust.
 * The backend rejects deleting an in-progress club (409); that calm
 * message is surfaced verbatim.
 */
function DeleteClubSection({
  onDeleteClub,
  deletingClub,
  deleteClubError,
}: {
  onDeleteClub: () => void;
  deletingClub: boolean;
  deleteClubError?: string | null;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <section className="mt-12 border-t border-border pt-6">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">delete club</h2>

      {confirming ? (
        <div className="mt-4 space-y-4">
          <p className="font-mono text-[13px] font-light text-muted">
            this removes the club and everything in it. it can't be undone.
          </p>
          <div className="flex items-center gap-4">
            {/* The screen's single Rust use: the destructive confirm. */}
            <Button
              variant="link"
              type="button"
              onClick={onDeleteClub}
              disabled={deletingClub}
            >
              {deletingClub ? "deleting…" : "delete this club"}
            </Button>
            <Button
              variant="ghost"
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deletingClub}
            >
              cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4">
          <Button variant="ghost" type="button" onClick={() => setConfirming(true)}>
            delete club
          </Button>
        </div>
      )}

      {deleteClubError ? (
        <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
          {deleteClubError}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Destructive action for anyone but the fixed organizer (plain members and,
 * since MYS-99, co-organizers too). Two-step confirm, mirrors
 * DeleteClubSection — but its confirm intentionally uses the `ghost`
 * Button variant, not `link` (Rust). A co-organizer can have this section
 * open at the same time as DeleteClubSection, which already spends this
 * screen's single Rust use; keeping this one in the Sage/ghost family avoids
 * a second Rust element appearing in the same view.
 */
function LeaveClubSection({
  onLeaveClub,
  leavingClub,
  leaveClubError,
}: {
  onLeaveClub: () => void;
  leavingClub: boolean;
  leaveClubError?: string | null;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <section className="mt-12 border-t border-border pt-6">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">leave club</h2>

      {confirming ? (
        <div className="mt-4 space-y-4">
          <p className="font-mono text-[13px] font-light text-muted">
            you'll lose access to this club's mystery mixes and results.
          </p>
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              type="button"
              onClick={onLeaveClub}
              disabled={leavingClub}
            >
              {leavingClub ? "leaving…" : "leave this club"}
            </Button>
            <Button
              variant="ghost"
              type="button"
              onClick={() => setConfirming(false)}
              disabled={leavingClub}
            >
              cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4">
          <Button variant="ghost" type="button" onClick={() => setConfirming(true)}>
            leave club
          </Button>
        </div>
      )}

      {leaveClubError ? (
        <p role="alert" className="mt-3 font-mono text-[11px] text-ink">
          {leaveClubError}
        </p>
      ) : null}
    </section>
  );
}

function MixesSection({
  mixes,
  mixResults,
  isAdmin,
  onOpenMix,
  onUpdateMix,
  savingMixId,
  updateMixError,
}: {
  mixes: Mix[];
  mixResults: Record<string, MixResults>;
  isAdmin: boolean;
  onOpenMix: (mixId: string) => void;
  onUpdateMix: (
    mixId: string,
    input: { theme?: string | null; description?: string | null },
  ) => Promise<boolean>;
  savingMixId: string | null;
  updateMixError?: string | null;
}) {
  // Mixes are auto-created with the club, so the slate always exists. The
  // empty state is a fallback only (e.g. a stale/odd club with zero mixes).
  return (
    <section className="mt-12">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        mystery mixes ({mixes.length})
      </h2>

      {mixes.length === 0 ? (
        <p className="mt-4 font-mono text-[13px] font-light text-muted">no mystery mixes yet</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {mixes.map((mix) => (
            <li key={mix.id}>
              <MixRow
                mix={mix}
                results={mixResults[mix.id]}
                isAdmin={isAdmin}
                onOpen={() => onOpenMix(mix.id)}
                onUpdate={(input) => onUpdateMix(mix.id, input)}
                saving={savingMixId === mix.id}
                error={savingMixId === mix.id ? updateMixError : null}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * One mix in the mixes list. State drives the visual weight, within the
 * Sage/Ink family only — no Rust here (the screen reserves its single Rust use
 * for the delete-club confirm):
 *  - active mix (open submission/voting) → Sage-pale fill, the eye lands here
 *  - upcoming (pending) → muted theme, quiet
 *  - closed → plain
 *
 * The heading is always "mix N". When the organizer has named the mix the
 * theme shows beneath it; an unnamed mix shows a quiet muted prompt to the
 * organizer (and nothing to members). Organizers can rename a `pending` mix
 * in place (theme + description); once it opens the API locks those fields
 * (409), so the edit affordance is replaced by a calm muted note.
 *
 * A closed mix also carries a compact reveal summary — the winner (top of the
 * vote leaderboard) and the most-noted pick — once its `results` have loaded.
 * Ties show every co-winner.
 */
function MixRow({
  mix,
  results,
  isAdmin,
  onOpen,
  onUpdate,
  saving,
  error,
}: {
  mix: Mix;
  results?: MixResults;
  isAdmin: boolean;
  onOpen: () => void;
  onUpdate: (input: { theme?: string | null; description?: string | null }) => Promise<boolean>;
  saving: boolean;
  error?: string | null;
}) {
  const [editing, setEditing] = useState(false);

  const active = isActiveMix(mix.state);
  const pending = mix.state === "pending";
  const named = !!mix.theme;

  if (editing) {
    return (
      <div className="rounded-[3px] border border-border bg-white px-5 py-5">
        <MixEditForm
          mix={mix}
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
              mystery mix {mix.mix_number}
            </span>
            {named ? (
              <span className="mt-0.5 block truncate font-serif text-[16px] text-ink">
                {mix.theme}
              </span>
            ) : isAdmin ? (
              <span className="mt-0.5 block truncate font-mono text-[13px] font-light italic text-muted">
                untitled — add a theme
              </span>
            ) : null}
          </span>
          <span className="shrink-0">
            <Badge>{MIX_STATE_LABEL[mix.state]}</Badge>
          </span>
        </div>
        {mix.description ? (
          <p className="mt-2 font-mono text-[11px] font-light leading-relaxed text-muted">
            {mix.description}
          </p>
        ) : null}
        {/* Submission progress while the mix is open for submissions (MYS-101). */}
        {mix.state === "open_submission" && mix.member_count > 0 ? (
          <p className="mt-2 font-mono uppercase tracking-label text-[9px] text-muted">
            {mix.submission_count} of {mix.member_count} submitted
          </p>
        ) : null}
        {/* Voting progress while the mix is open for voting (MYS-110). */}
        {mix.state === "open_voting" && mix.voting_eligible_count > 0 ? (
          <p className="mt-2 font-mono uppercase tracking-label text-[9px] text-muted">
            {mix.voted_count} of {mix.voting_eligible_count} voted
          </p>
        ) : null}
        {/* Prominent, phase-appropriate deadline chip (MYS-161) — viewer-local
            time. Renders nothing for legacy mixes with no deadline set. */}
        <DeadlineChip mix={mix} className="mt-3" />
        {/* Viewer participation indicators — subtle sage checkmarks. */}
        {mix.viewer_submitted || mix.viewer_voted ? (
          <p className="mt-1.5 flex items-center gap-3 font-mono uppercase tracking-label text-[9px] text-sage">
            {mix.viewer_submitted ? <ViewerCheck label="you submitted" /> : null}
            {mix.viewer_voted ? <ViewerCheck label="you voted" /> : null}
          </p>
        ) : null}
        {mix.state === "closed" && results ? <ClosedMixSummary results={results} /> : null}
      </button>

      {isAdmin ? (
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
              theme locks once a mystery mix opens
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
      <CheckmarkIcon />
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
 * Compact reveal summary for a closed mix's card: the winner (top of the vote
 * leaderboard) and the most-noted pick. Both can tie — every co-winner is named.
 * Label-left / value-right, staying in the Sage/Ink family (no Rust here — the
 * screen reserves its single Rust use for the delete-club confirm).
 */
function ClosedMixSummary({ results }: { results: MixResults }) {
  const winners = topVoteWinners(results.leaderboard);
  const mostNoted = results.most_noted.winners;
  if (winners.length === 0 && mostNoted.length === 0) return null;

  return (
    <dl className="mt-3 space-y-2 border-t border-border pt-3">
      {winners.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="flex shrink-0 items-center gap-1 font-mono uppercase tracking-label text-[9px] text-muted">
            <CrownIcon className="text-gold" />
            {winners.length > 1 ? "winners" : "winner"}
          </dt>
          <dd className="min-w-0 text-right font-mono text-[13px] font-light text-ink">
            {winners.map((w) => w.display_name).join(" & ")}
          </dd>
        </div>
      ) : null}
      {mostNoted.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="flex shrink-0 items-center gap-1 font-mono uppercase tracking-label text-[9px] text-muted">
            <CrownIcon className="text-gold" />
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
 * Inline theme + description editor for a single pending mix, shown in place
 * within the mixes list. Underline inputs only (TextField + an underline
 * textarea), matching the mix-detail editor. No Rust — this screen's single
 * Rust use is the delete-club confirm.
 */
function MixEditForm({
  mix,
  saving,
  error,
  onCancel,
  onSave,
}: {
  mix: Mix;
  saving: boolean;
  error?: string | null;
  onCancel: () => void;
  onSave: (input: { theme?: string | null; description?: string | null }) => void;
}) {
  const [theme, setTheme] = useState(mix.theme ?? "");
  const [description, setDescription] = useState(mix.description ?? "");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const input: { theme?: string | null; description?: string | null } = {};

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
      onCancel();
      return;
    }
    onSave(input);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
        mystery mix {mix.mix_number}
      </span>

      <TextField
        id={`mix-theme-${mix.id}`}
        label="theme"
        name="theme"
        placeholder="late summer feels"
        value={theme}
        onChange={(e) => setTheme(e.target.value)}
        disabled={saving}
        autoComplete="off"
      />

      <label htmlFor={`mix-description-${mix.id}`} className="block">
        <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
          description
        </span>
        <textarea
          id={`mix-description-${mix.id}`}
          rows={2}
          placeholder="a line or two of color for this mystery mix"
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
  club,
  onUpdateClub,
  updating,
  updateError,
}: {
  club: Club;
  onUpdateClub: ClubHomeScreenProps["onUpdateClub"];
  updating: boolean;
  updateError?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(club.name);
  const [description, setDescription] = useState(club.description ?? "");
  const [totalMixes, setTotalMixes] = useState(String(club.total_mixes));
  const initialSubmissionWindow = hoursToDaysAndHours(club.submission_window_hours);
  const initialVotingWindow = hoursToDaysAndHours(club.voting_window_hours);
  const [submissionWindowDays, setSubmissionWindowDays] = useState(
    String(initialSubmissionWindow.days),
  );
  const [submissionWindowHours, setSubmissionWindowHours] = useState(
    String(initialSubmissionWindow.hours),
  );
  const [votingWindowDays, setVotingWindowDays] = useState(String(initialVotingWindow.days));
  const [votingWindowHours, setVotingWindowHours] = useState(String(initialVotingWindow.hours));
  const [windowError, setWindowError] = useState<string | null>(null);

  function openForm() {
    setName(club.name);
    setDescription(club.description ?? "");
    setTotalMixes(String(club.total_mixes));
    const submissionWindow = hoursToDaysAndHours(club.submission_window_hours);
    setSubmissionWindowDays(String(submissionWindow.days));
    setSubmissionWindowHours(String(submissionWindow.hours));
    const votingWindow = hoursToDaysAndHours(club.voting_window_hours);
    setVotingWindowDays(String(votingWindow.days));
    setVotingWindowHours(String(votingWindow.hours));
    setWindowError(null);
    setOpen(true);
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const input: {
      name?: string;
      description?: string | null;
      total_mixes?: number;
      submission_window_hours?: number;
      voting_window_hours?: number;
    } = {};

    const trimmedName = name.trim();
    if (trimmedName && trimmedName !== club.name) input.name = trimmedName;

    const trimmedDescription = description.trim();
    const currentDescription = club.description ?? "";
    if (trimmedDescription !== currentDescription) {
      input.description = trimmedDescription ? trimmedDescription : null;
    }

    const mixes = Number(totalMixes);
    if (Number.isFinite(mixes) && mixes >= 1 && mixes !== club.total_mixes) {
      input.total_mixes = mixes;
    }

    const submissionHours = daysAndHoursToTotal(
      Number(submissionWindowDays),
      Number(submissionWindowHours),
    );
    const votingHours = daysAndHoursToTotal(Number(votingWindowDays), Number(votingWindowHours));
    const submissionWindowValidationError = validateWindowHours(submissionHours);
    if (submissionWindowValidationError) {
      setWindowError(`submission ${submissionWindowValidationError}`);
      return;
    }
    const votingWindowValidationError = validateWindowHours(votingHours);
    if (votingWindowValidationError) {
      setWindowError(`voting ${votingWindowValidationError}`);
      return;
    }
    setWindowError(null);
    if (submissionHours !== club.submission_window_hours) {
      input.submission_window_hours = submissionHours;
    }
    if (votingHours !== club.voting_window_hours) {
      input.voting_window_hours = votingHours;
    }

    onUpdateClub(input);
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
        id="edit-club-name"
        label="name"
        name="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={updating}
      />
      <TextField
        id="edit-club-description"
        label="description"
        name="description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={updating}
      />
      <TextField
        id="edit-club-total-mixes"
        label="mystery mixes"
        name="total_mixes"
        type="number"
        min={1}
        value={totalMixes}
        onChange={(e) => setTotalMixes(e.target.value)}
        disabled={updating}
      />
      <DeadlineWindowField
        idPrefix="edit-submission-window"
        label="submission window"
        days={submissionWindowDays}
        hours={submissionWindowHours}
        onDaysChange={setSubmissionWindowDays}
        onHoursChange={setSubmissionWindowHours}
        disabled={updating}
      />
      <DeadlineWindowField
        idPrefix="edit-voting-window"
        label="voting window"
        days={votingWindowDays}
        hours={votingWindowHours}
        onDaysChange={setVotingWindowDays}
        onHoursChange={setVotingWindowHours}
        disabled={updating}
      />
      <p className="font-mono text-[11px] font-light text-muted">
        this only applies going forward — a mystery mix already collecting submissions or
        votes keeps its current deadline. it takes effect the next time a mystery mix (or
        its next phase) opens.
      </p>
      {windowError ? (
        <p role="alert" className="font-mono text-[11px] text-ink">
          {windowError}
        </p>
      ) : null}
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

