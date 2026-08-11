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
import { Card } from "../components/Card";
import { PaperSurface } from "../components/PaperSurface";
import { ClubName } from "../components/ClubName";
import { FormError } from "../components/FormError";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { CrownIcon } from "../components/CrownIcon";
import { Confetti } from "../components/Confetti";
import { DeadlineChip } from "../components/DeadlineChip";
import { DeadlineWindowField } from "../components/DeadlineWindowField";
import { InviteShare } from "../components/InviteShare";
import { UserAvatar } from "../components/avatars/UserAvatar";
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
      <PaperSurface nested>
        <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
          <ConcentricRings size={88} spinning onPaper className="mx-auto" />
        </main>
      </PaperSurface>
    );
  }

  if (error) {
    return (
      // A failed *load*, not a form error: the club never resolved, so this is
      // the whole content of the screen rather than a message about a field.
      // ADR 0004's `destructive-text` category is for form validation, so this
      // stays plain `foreground` — and it deliberately keeps no `role="alert"`,
      // since it is present on first paint rather than announced later.
      <PaperSurface nested>
        <main className="flex flex-1 flex-col items-center justify-center px-4 text-center sm:px-8">
          <p className="text-sm leading-[1.72] text-ink">{error}</p>
          <div className="mt-6">
            <Button variant="ghost" onPaper type="button" onClick={onBack}>
              back
            </Button>
          </div>
        </main>
      </PaperSurface>
    );
  }

  // Amber budget (category rule, not a count). This screen spends amber in
  // exactly three in-category ways, and nowhere decorative:
  //  - ACTION: the delete-club confirm now takes `Button variant="destructive"`
  //    instead of the amber `link` variant — a delete is not amber's category —
  //    so the only amber actions left are hover/focus states, which are
  //    transient and one-at-a-time.
  //  - ACHIEVEMENT: rank 1 of the all-time standings, which is bounded to a
  //    single row because there is exactly one standings table here.
  //  - ACTION: `DeadlineChip`, which grades its own urgency and goes amber only
  //    while a deadline is actually closing — and the API allows at most one
  //    active mix per club, so at most one chip on the screen can be amber.
  // Nothing per-mix-row and nothing per-member-row carries amber, because both
  // lists are unbounded enough that a per-row accent would read as pattern.
  // The shared TopNav is rendered by AuthedLayout, so this is content-only.
  const isComplete = club.state === "complete";

  return (
    // The light surface (ADR 0013), same frame model as /home: the page is
    // `paper`, every card stays dark. `nested` because this screen sits under
    // AuthedLayout, which already fills the viewport below the nav.
    <PaperSurface nested>
      <main className="mx-auto w-full max-w-lg px-4 pt-8 pb-16 sm:px-8">
        {isComplete ? <Confetti /> : null}
        <div className="flex items-start justify-between gap-4">
          <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
            {/* `onPaper`: the accented second word is 2.62:1 as `accent` here,
                and this is ordinary title text rather than large-display type,
                so it owes the full 4.5:1. */}
            <ClubName name={club.name} onPaper />
          </h1>
          <div className="shrink-0 pt-2">
            <Badge>{club.state}</Badge>
          </div>
        </div>
        {club.description ? (
          <p className="mt-2 text-sm leading-[1.72] text-ink-muted">{club.description}</p>
        ) : null}
        {/* Mono at normal tracking is the system's signature for a value, which
            is what a mix counter is. */}
        <p className="mt-3 font-mono text-meta text-ink-muted">
          mix {club.current_mix} of {club.total_mixes}
        </p>
        {isComplete ? (
          <p className="mt-4 text-base leading-[1.72] text-ink-muted">this club has wrapped.</p>
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

        {/* Members / all-time leaderboard (MYS-157) — the style tile's ScoreRow:
            rank numeral, avatar, name, a thin progress track, and a
            right-aligned mono score. This is the screen's ONLY standings table,
            so its rank-1 amber is bounded to one row and stays achievement
            rather than pattern (unlike the per-mix winner lines further up,
            which repeat once per closed mix and therefore stay neutral).
            The bar and the rank column only appear once somebody actually has a
            vote — with a scoreless roster there is no achievement to mark, so
            no amber and no empty rails. */}
        <section className="mt-12">
          <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
            members ({members.length})
          </h2>
          <ul className="mt-4 space-y-2">
            {leaderboard.map((entry) => {
              const member = members.find((m) => m.user_id === entry.user_id);
              const isMe = entry.user_id === userId;
              // The fixed organizer's role can't be toggled or removed by anyone
              // (MYS-99) — every other member, including other co-organizers, is
              // fair game for any current admin.
              const showRoleAndRemove = isAdmin && member && !member.is_organizer;
              const anyVotes = leaderboard.some((e) => e.vote_count > 0);
              // Ranks are sequential, so rank 1 always holds the top vote count
              // and its bar always reads 100%.
              const topVotes = leaderboard[0]?.vote_count ?? 0;
              const leading = anyVotes && entry.rank === 1;
              return (
                <li
                  key={entry.user_id}
                  className={[
                    // `text-foreground` anchors this row to the DARK ramp, the
                    // same way `Card` does and for the same reason (ADR 0013):
                    // these are dark islands on a light page, and anything inside
                    // that merely inherits would pick up `ink` and render at
                    // 1.65:1. It is a hand-rolled surface rather than a `Card`,
                    // so it has to say so itself.
                    "rounded-hair border px-4 py-3 text-foreground",
                    leading
                      ? "border-accent-hairline bg-accent-surface"
                      : "border-hairline-soft bg-card",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between gap-4">
                    <span className="flex items-center gap-3">
                      <span className="w-6 shrink-0 text-right font-mono text-mini text-muted-foreground">
                        {anyVotes ? (
                          entry.rank === 1 ? (
                            <CrownIcon className="h-3.5 w-3.5 text-accent" />
                          ) : (
                            `#${entry.rank}`
                          )
                        ) : null}
                      </span>
                      <UserAvatar userId={entry.user_id} size={28} />
                      <span
                        className={`font-mono text-sm text-foreground ${isMe ? "font-medium" : ""}`}
                      >
                        {entry.display_name}
                      </span>
                      {member?.is_organizer ? <Badge>organizer</Badge> : null}
                      {member?.is_admin && !member?.is_organizer ? (
                        <Badge>co-organizer</Badge>
                      ) : null}
                    </span>
                    <span className="flex items-center gap-4">
                      <span
                        className={`text-right font-mono text-xs ${leading ? "text-accent" : "text-muted-foreground"}`}
                      >
                        {entry.vote_count} {entry.vote_count === 1 ? "vote" : "votes"}
                      </span>
                      {showRoleAndRemove ? (
                        <button
                          type="button"
                          onClick={() =>
                            onChangeMemberRole(entry.user_id, member.is_admin ? "member" : "admin")
                          }
                          disabled={changingRoleUserId === entry.user_id}
                          className="py-1.5 font-mono uppercase tracking-mono text-mini text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
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
                          className="py-1.5 font-mono uppercase tracking-mono text-mini text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link disabled:cursor-not-allowed disabled:text-muted-foreground disabled:no-underline"
                        >
                          {removingUserId === entry.user_id ? "removing…" : "remove"}
                        </button>
                      ) : null}
                    </span>
                  </div>
                  {/* The tile runs the bar inline between name and score; it
                      moves to its own line here because these rows also carry
                      role badges and two admin controls, which leave no room
                      for a legible track at this column width. */}
                  {anyVotes ? (
                    <div
                      aria-hidden="true"
                      className="mt-2 h-0.5 w-full overflow-hidden rounded-hair bg-track"
                    >
                      <div
                        className={`h-full rounded-hair ${leading ? "bg-accent" : "bg-muted-foreground"}`}
                        style={{
                          width: `${topVotes > 0 ? (entry.vote_count / topVotes) * 100 : 0}%`,
                        }}
                      />
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
          {roleChangeError ? (
            <div className="mt-3">
              <FormError onPaper>{roleChangeError}</FormError>
            </div>
          ) : null}
          {removeError ? (
            <div className="mt-3">
              <FormError onPaper>{removeError}</FormError>
            </div>
          ) : null}
        </section>

        {/* Invite share — a single shareable link. Admin-only (MYS-246): the
            backend now rejects a non-admin's create-invite call, so a plain
            member must not even see the option. */}
        {isAdmin ? (
          <section className="mt-12">
            <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
              invite
            </h2>
            <div className="mt-4">
              {inviteUrl ? (
                <InviteShare inviteUrl={inviteUrl} />
              ) : (
                <>
                  <Button
                    onPaper
                    type="button"
                    onClick={onGenerateInvite}
                    disabled={generatingInvite}
                  >
                    {generatingInvite ? "generating…" : "invite"}
                  </Button>
                  <p className="mt-3 text-meta leading-[1.6] text-ink-muted">
                    a shareable link, good for 48 hours.
                  </p>
                </>
              )}
            </div>
            {inviteError ? (
              <div className="mt-3">
                <FormError onPaper>{inviteError}</FormError>
              </div>
            ) : null}
          </section>
        ) : null}

        {/* Destructive actions (MYS-99): any admin (fixed organizer or
            co-organizer) can delete the club outright. The fixed organizer
            can never leave (the backend guard blocks it) so they only see
            delete; a co-organizer is the one case that sees both — they can
            leave individually, or delete the whole club; a plain member
            only sees leave. Delete is irreversible and takes the
            `destructive` fill (see DeleteClubSection); leaving is reversible
            by re-invite, so LeaveClubSection stays `ghost`. Neither is amber,
            and the two now read as different weights of severity rather than
            competing for one accent budget. */}
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
    </PaperSurface>
  );
}

/**
 * Admin-only destructive action — the fixed organizer or any co-organizer
 * (MYS-99). A two-step confirm (calm copy, no exclamation marks): the first
 * action arms the confirm, the second commits. The commit takes
 * `Button variant="destructive"` (R2), replacing the amber `link` variant it
 * used to carry: amber means action or achievement, and an irreversible delete
 * is neither in the sense that matters. The backend rejects deleting an
 * in-progress club (409); that calm message is surfaced verbatim.
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
    <section className="mt-12 border-t border-ink-hairline pt-6">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
        delete club
      </h2>

      {confirming ? (
        <div className="mt-4 space-y-4">
          <p className="text-sm leading-[1.72] text-ink-muted">
            this removes the club and everything in it. it can't be undone.
          </p>
          <div className="flex items-center gap-4">
            {/* The one irreversible action on this screen: a `destructive`
                fill, never the amber `link` variant it used to carry. */}
            <Button
              variant="destructive"
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
          <Button onPaper variant="ghost" type="button" onClick={() => setConfirming(true)}>
            delete club
          </Button>
        </div>
      )}

      {deleteClubError ? (
        <div className="mt-3">
          <FormError onPaper>{deleteClubError}</FormError>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Destructive action for anyone but the fixed organizer (plain members and,
 * since MYS-99, co-organizers too). Two-step confirm, mirrors
 * DeleteClubSection — but its confirm stays on the `ghost` variant rather
 * than taking `destructive`. Leaving is recoverable (an admin can re-invite
 * you) where deleting a club is not, and a co-organizer sees both sections at
 * once: giving them the same red fill would flatten that difference into one
 * undifferentiated danger zone.
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
    <section className="mt-12 border-t border-ink-hairline pt-6">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
        leave club
      </h2>

      {confirming ? (
        <div className="mt-4 space-y-4">
          <p className="text-sm leading-[1.72] text-ink-muted">
            you'll lose access to this club's mystery mixes and results.
          </p>
          <div className="flex items-center gap-4">
            <Button
              onPaper
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
          <Button onPaper variant="ghost" type="button" onClick={() => setConfirming(true)}>
            leave club
          </Button>
        </div>
      )}

      {leaveClubError ? (
        <div className="mt-3">
          <FormError onPaper>{leaveClubError}</FormError>
        </div>
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
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
        mystery mixes ({mixes.length})
      </h2>

      {mixes.length === 0 ? (
        <p className="mt-4 text-sm leading-[1.72] text-ink-muted">no mystery mixes yet</p>
      ) : (
        <ul className="mt-4 space-y-4">
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
 * One mix in the mixes list, on R8's list-card pattern: a `Card` surface with
 * the pure-CSS hover lift, a mono eyebrow, a `font-display` uppercase title,
 * and a mono meta row.
 *
 * **No amber on a mix row, in any state.** State drives weight through
 * elevation and foreground brightness instead:
 *  - active mix (open submission/voting) → `shadow-z3` at rest and a
 *    `foreground` eyebrow, so the row the member can act on is literally the
 *    highest and brightest thing in the list
 *  - upcoming (pending) → resting card, muted eyebrow
 *  - closed → resting card, muted eyebrow
 *
 * The style guide does list "mix/season numbers" among amber's uses, and the
 * API allows only one active mix per club, so an amber eyebrow on the active
 * row would be bounded. It is still not taken: `DeadlineChip` already owns the
 * amber on exactly that row (it goes amber while the deadline is closing), and
 * a second amber source in the same row would make the accent read as the
 * row's styling rather than as its urgency. Elevation is the system's own
 * answer for hierarchy in the dark, and it costs no accent.
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
      <Card>
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
      </Card>
    );
  }

  return (
    <Card
      className={[
        "transition-[box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:shadow-z3",
        // One step of extra rest elevation for the single row that can be acted
        // on. `shadow-z3` is emitted after `shadow-z2` in the config's shadow
        // scale, so it wins over the one baked into `Card`.
        active ? "shadow-z3" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button type="button" onClick={onOpen} className="block w-full text-left">
        <div className="flex items-start justify-between gap-4">
          <span className="min-w-0">
            <span
              className={[
                "block font-mono uppercase tracking-mono-caps text-mini",
                active ? "text-foreground" : "text-muted-foreground",
              ].join(" ")}
            >
              mystery mix {mix.mix_number}
            </span>
            {named ? (
              <span
                className="mt-2 block truncate font-display text-sm font-bold uppercase leading-none"
                title={mix.theme ?? undefined}
              >
                {mix.theme}
              </span>
            ) : isAdmin ? (
              <span className="mt-2 block truncate text-sm italic leading-[1.65] text-muted-foreground">
                untitled — add a theme
              </span>
            ) : null}
          </span>
          <span className="shrink-0">
            <Badge>{MIX_STATE_LABEL[mix.state]}</Badge>
          </span>
        </div>
        {mix.description ? (
          <p className="mt-2 text-sm leading-[1.65] text-muted-foreground">{mix.description}</p>
        ) : null}
        {/* Submission progress while the mix is open for submissions (MYS-101). */}
        {mix.state === "open_submission" && mix.member_count > 0 ? (
          <p className="mt-2 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            {mix.submission_count} of {mix.member_count} submitted
          </p>
        ) : null}
        {/* Voting progress while the mix is open for voting (MYS-110). */}
        {mix.state === "open_voting" && mix.voting_eligible_count > 0 ? (
          <p className="mt-2 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            {mix.voted_count} of {mix.voting_eligible_count} voted
          </p>
        ) : null}
        {/* Prominent, phase-appropriate deadline chip (MYS-161) — viewer-local
            time. Renders nothing for legacy mixes with no deadline set. This is
            the only element in the row that may go amber, and only while the
            deadline is closing. */}
        <DeadlineChip mix={mix} className="mt-3" />
        {/* Viewer participation indicators. `foreground` rather than the accent:
            "you already did this" is a completed fact, not an action or an
            achievement, and it can appear on every row at once. */}
        {mix.viewer_submitted || mix.viewer_voted ? (
          <p className="mt-1.5 flex items-center gap-3 font-mono uppercase tracking-mono-caps text-mini text-foreground">
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
              className="font-mono uppercase tracking-mono text-mini text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link"
            >
              {named ? "edit" : "add a theme"}
            </button>
          ) : (
            <p className="text-meta leading-[1.6] text-muted-foreground">
              theme locks once a mystery mix opens
            </p>
          )}
        </div>
      ) : null}
    </Card>
  );
}

/** Small checkmark with a visible label, screened from AT so only the label
 *  text is announced. Inherits its color from the row above it. */
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
 * Label-left / value-right.
 *
 * **The crowns stay neutral.** Amber's category does cover achievement, so a
 * single winner line would be in category — but this block renders once per
 * closed mix, and a finished club shows one for every mix it ran (up to the
 * 50-mix cap the create form enforces). A column of amber crowns is amber as
 * pattern, which the category rule forbids however in-category each individual
 * line is. Same conclusion R8 reached about completed club cards, and the same
 * treatment: a `muted-foreground` crown glyph carries the meaning without
 * degrading with count. The screen's one achievement accent belongs to rank 1
 * of the standings, which is bounded to a single row.
 */
function ClosedMixSummary({ results }: { results: MixResults }) {
  const winners = topVoteWinners(results.leaderboard);
  const mostNoted = results.most_noted.winners;
  if (winners.length === 0 && mostNoted.length === 0) return null;

  return (
    <dl className="mt-3 space-y-2 border-t border-hairline-soft pt-3">
      {winners.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="flex shrink-0 items-center gap-1 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            <CrownIcon className="text-muted-foreground" />
            {winners.length > 1 ? "winners" : "winner"}
          </dt>
          <dd className="min-w-0 text-right font-mono text-sm text-foreground">
            {winners.map((w) => w.display_name).join(" & ")}
          </dd>
        </div>
      ) : null}
      {mostNoted.length > 0 ? (
        <div className="flex items-baseline justify-between gap-4">
          <dt className="flex shrink-0 items-center gap-1 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            <CrownIcon className="text-muted-foreground" />
            most noted
          </dt>
          <dd className="min-w-0 text-right font-mono text-sm text-foreground">
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
 * textarea whose resting/focus/label treatment is copied from TextField, since
 * there is no textarea primitive).
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

  const errorId = `mix-edit-error-${mix.id}`;

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-5">
      <span className="block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
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
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
      />

      <label htmlFor={`mix-description-${mix.id}`} className="block">
        <span className="block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
          description
        </span>
        {/* Resting underline is `muted-foreground`, not `hairline`: when the
            underline IS the affordance, WCAG 1.4.11 applies and a ~1.2:1
            hairline fails it. `focus:outline-none` is only acceptable because
            `focus:border-accent` replaces the indicator it removes. Matches
            TextField exactly, including having no disabled recolor. */}
        <textarea
          id={`mix-description-${mix.id}`}
          rows={2}
          placeholder="a line or two of color for this mystery mix"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={saving}
          className="mt-2 w-full resize-none rounded-none border-0 border-b border-muted-foreground bg-transparent px-0 py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:border-accent focus:outline-none"
        />
      </label>

      {error ? <FormError id={errorId}>{error}</FormError> : null}

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
  const [windowErrorField, setWindowErrorField] = useState<
    "submission_window" | "voting_window" | null
  >(null);

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
      setWindowErrorField("submission_window");
      return;
    }
    const votingWindowValidationError = validateWindowHours(votingHours);
    if (votingWindowValidationError) {
      setWindowError(`voting ${votingWindowValidationError}`);
      setWindowErrorField("voting_window");
      return;
    }
    setWindowError(null);
    setWindowErrorField(null);
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
        <Button onPaper variant="ghost" type="button" onClick={openForm}>
          edit
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
      <TextField
        onPaper
        id="edit-club-name"
        label="name"
        name="name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={updating}
      />
      <TextField
        onPaper
        id="edit-club-description"
        label="description"
        name="description"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={updating}
      />
      <TextField
        onPaper
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
        onPaper
        idPrefix="edit-submission-window"
        label="submission window"
        days={submissionWindowDays}
        hours={submissionWindowHours}
        onDaysChange={setSubmissionWindowDays}
        onHoursChange={setSubmissionWindowHours}
        disabled={updating}
        error={windowErrorField === "submission_window" ? windowError : null}
      />
      <DeadlineWindowField
        onPaper
        idPrefix="edit-voting-window"
        label="voting window"
        days={votingWindowDays}
        hours={votingWindowHours}
        onDaysChange={setVotingWindowDays}
        onHoursChange={setVotingWindowHours}
        disabled={updating}
        error={windowErrorField === "voting_window" ? windowError : null}
      />
      <p className="text-meta leading-[1.6] text-ink-muted">
        this only applies going forward — a mystery mix already collecting submissions or votes
        keeps its current deadline. it takes effect the next time a mystery mix (or its next phase)
        opens.
      </p>
      {/* A failed save is a screen-level form error (ADR 0004) — its own color
          category, so it consumes nothing from this screen's amber and may show
          at the same time as either window field's own inline message. */}
      {updateError ? <FormError onPaper>{updateError}</FormError> : null}
      <div className="flex items-center gap-4">
        <Button onPaper type="submit" disabled={updating}>
          {updating ? "saving…" : "save"}
        </Button>
        <Button
          onPaper
          variant="ghost"
          type="button"
          onClick={() => setOpen(false)}
          disabled={updating}
        >
          cancel
        </Button>
      </div>
    </form>
  );
}
