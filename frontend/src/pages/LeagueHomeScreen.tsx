import { type FormEvent, useEffect, useState } from "react";
import type { League, LeagueMember } from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

type LeagueHomeScreenProps = {
  league: League;
  members: LeagueMember[];
  isOrganizer: boolean;
  loading: boolean;
  error?: string | null;
  onBack: () => void;
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
  isOrganizer,
  loading,
  error,
  onBack,
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

        {/* Members */}
        <section className="mt-12">
          <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
            members ({members.length})
          </h2>
          <ul className="mt-4 divide-y divide-border border-t border-border">
            {members.map((member) => {
              const showRemove = isOrganizer && !member.is_organizer;
              return (
                <li
                  key={member.user_id}
                  className="flex items-center justify-between gap-4 py-3"
                >
                  <span className="flex items-center gap-3">
                    <span className="font-mono text-[13px] text-ink">
                      {member.display_name}
                    </span>
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
