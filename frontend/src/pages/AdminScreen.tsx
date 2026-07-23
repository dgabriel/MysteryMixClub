import { type FormEvent, useState } from "react";
import type { AdminUser, SpotifyStatus, WaitlistEntry } from "../services/api";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { InviteShare } from "../components/InviteShare";
import { TextField } from "../components/TextField";

/** Copy for the one-time `?spotify=` flag the OAuth callback lands back with. */
function spotifyResultMessage(flag: string | null): string | null {
  switch (flag) {
    case "connected":
      return "spotify connected.";
    case "denied":
      return "spotify authorization was cancelled.";
    case null:
      return null;
    default:
      return "something went wrong connecting spotify. try again.";
  }
}

type AdminScreenProps = {
  query: string;
  onQueryChange: (value: string) => void;
  onSearch: () => void;
  searching: boolean;
  results: AdminUser[];
  /** True once a search has run, so an empty result reads "no matches" rather
   *  than the pre-search blank. */
  searched: boolean;
  searchError?: string | null;
  onDeleteUser: (userId: string) => void;
  deletingUserId: string | null;
  deleteError?: string | null;
  /** Platform invite (MYS-182): grants signup only, no club attachment. */
  platformInviteUrl: string | null;
  generatingInvite: boolean;
  inviteError?: string | null;
  onGenerateInvite: () => void;
  /** Waitlist (MYS-215, temporary). */
  waitlistEntries: WaitlistEntry[];
  waitlistLoading: boolean;
  waitlistError?: string | null;
  invitingEntryId: string | null;
  onInviteFromWaitlist: (entryId: string) => void;
  /** Spotify shared-account connect (MYS-169), ops-only. */
  spotifyStatus: SpotifyStatus | null;
  spotifyStatusLoading: boolean;
  connectingSpotify: boolean;
  spotifyError?: string | null;
  spotifyResult: string | null;
  onConnectSpotify: () => void;
};

/**
 * Thin platform-admin page: search users by email, then hard-delete a match
 * behind a typed confirm; and generate a club-less signup invite (MYS-182).
 * Content-only — the shared TopNav is rendered by AuthedLayout. The single
 * Rust signal on this screen is the destructive confirm action; everything
 * else, including the invite section, stays in the Sage/Ink family.
 * Underline-only inputs, ALL-CAPS labels, calm lowercase copy.
 */
export function AdminScreen({
  query,
  onQueryChange,
  onSearch,
  searching,
  results,
  searched,
  searchError,
  onDeleteUser,
  deletingUserId,
  deleteError,
  platformInviteUrl,
  generatingInvite,
  inviteError,
  onGenerateInvite,
  waitlistEntries,
  waitlistLoading,
  waitlistError,
  invitingEntryId,
  onInviteFromWaitlist,
  spotifyStatus,
  spotifyStatusLoading,
  connectingSpotify,
  spotifyError,
  spotifyResult,
  onConnectSpotify,
}: AdminScreenProps) {
  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSearch();
  }

  return (
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      <h1 className="font-serif lowercase text-[28px] leading-tight text-ink">admin</h1>
      <p className="mt-4 font-mono text-[13px] font-light text-muted">
        find a user by email, then remove their account and all of their data.
      </p>

      <form onSubmit={handleSubmit} className="mt-8 flex items-end gap-4">
        <div className="flex-1">
          <TextField
            id="admin-user-search"
            label="email"
            type="search"
            name="email"
            autoComplete="off"
            placeholder="name@example.com"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            disabled={searching}
          />
        </div>
        <Button type="submit" disabled={searching || !query.trim()}>
          {searching ? "searching…" : "search"}
        </Button>
      </form>

      {searchError ? (
        <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
          {searchError}
        </p>
      ) : null}

      <div className="mt-8">
        {searched && results.length === 0 && !searching ? (
          <p className="font-mono text-[13px] font-light text-muted">no matches</p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {results.map((user) => (
              <li key={user.id} className="py-4">
                <AdminUserRow
                  user={user}
                  deleting={deletingUserId === user.id}
                  onDelete={() => onDeleteUser(user.id)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>

      {deleteError ? (
        <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
          {deleteError}
        </p>
      ) : null}

      <section className="mt-16">
        <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">invite</h2>
        <p className="mt-2 font-mono text-[13px] font-light text-muted">
          generate a signup invite. no club attached — whoever uses it creates their own, or later
          joins an open one.
        </p>

        {inviteError ? (
          <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
            {inviteError}
          </p>
        ) : null}

        <div className="mt-6">
          {platformInviteUrl ? (
            <InviteShare inviteUrl={platformInviteUrl} />
          ) : (
            <Button type="button" onClick={onGenerateInvite} disabled={generatingInvite}>
              {generatingInvite ? "generating…" : "generate invite"}
            </Button>
          )}
        </div>
      </section>

      <section className="mt-16">
        <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">waitlist</h2>
        <p className="mt-2 font-mono text-[13px] font-light text-muted">
          temporary, pre-launch. inviting a waitlist entry sends them a signup invite by email — the
          same kind generated above.
        </p>

        {waitlistError ? (
          <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
            {waitlistError}
          </p>
        ) : null}

        <div className="mt-6">
          {waitlistLoading ? null : waitlistEntries.length === 0 ? (
            <p className="font-mono text-[13px] font-light text-muted">
              no one on the waitlist yet
            </p>
          ) : (
            <WaitlistList
              entries={waitlistEntries}
              invitingEntryId={invitingEntryId}
              onInviteFromWaitlist={onInviteFromWaitlist}
            />
          )}
        </div>
      </section>

      <section className="mt-16">
        <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">spotify</h2>
        <p className="mt-2 font-mono text-[13px] font-light text-muted">
          connect the one shared mysterymixclub spotify account playlist generation runs under.
        </p>

        {spotifyResultMessage(spotifyResult) ? (
          <p className="mt-4 font-mono text-[11px] text-ink">
            {spotifyResultMessage(spotifyResult)}
          </p>
        ) : null}

        {spotifyError ? (
          <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
            {spotifyError}
          </p>
        ) : null}

        <div className="mt-6">
          {spotifyStatusLoading ? null : (
            <div className="flex items-center gap-4">
              <Badge>
                {!spotifyStatus?.configured
                  ? "not configured"
                  : spotifyStatus.connected
                    ? "connected"
                    : "not connected"}
              </Badge>
              <Button
                type="button"
                onClick={onConnectSpotify}
                disabled={connectingSpotify || !spotifyStatus?.configured}
              >
                {connectingSpotify
                  ? "connecting…"
                  : spotifyStatus?.connected
                    ? "reconnect spotify"
                    : "connect spotify"}
              </Button>
            </div>
          )}
        </div>
      </section>
    </main>
  );
}

type WaitlistStatusFilter = "all" | "pending" | "invited";

/**
 * Client-side search + status filter over the already-fetched waitlist
 * (MYS-215). Kept out of AdminRoute — this operates purely on data that's
 * already on the page, not a re-fetch, so it stays a display-layer concern
 * local to this component. Backend pagination would only be worth it if the
 * list grew into the thousands; this list is bounded by the same pre-launch
 * audience as the beta user cap.
 */
function WaitlistList({
  entries,
  invitingEntryId,
  onInviteFromWaitlist,
}: {
  entries: WaitlistEntry[];
  invitingEntryId: string | null;
  onInviteFromWaitlist: (entryId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<WaitlistStatusFilter>("all");

  const normalizedQuery = query.trim().toLowerCase();
  const filtered = entries.filter((entry) => {
    const matchesQuery = entry.email.toLowerCase().includes(normalizedQuery);
    const matchesStatus =
      status === "all"
        ? true
        : status === "invited"
          ? entry.invited_at !== null
          : entry.invited_at === null;
    return matchesQuery && matchesStatus;
  });

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0 flex-1">
          <TextField
            id="admin-waitlist-search"
            label="search"
            type="search"
            name="waitlist-search"
            autoComplete="off"
            placeholder="name@example.com"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex gap-4 pb-[10px]">
          {(["all", "pending", "invited"] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setStatus(option)}
              aria-pressed={status === option}
              className={[
                "font-mono uppercase tracking-ui text-[11px] transition-colors duration-150",
                status === option
                  ? "text-sage underline underline-offset-[3px]"
                  : "text-muted hover:text-ink",
              ].join(" ")}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6">
        {filtered.length === 0 ? (
          <p className="font-mono text-[13px] font-light text-muted">no matches</p>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {filtered.map((entry) => (
              <li key={entry.id} className="py-4">
                <WaitlistRow
                  entry={entry}
                  inviting={invitingEntryId === entry.id}
                  onInvite={() => onInviteFromWaitlist(entry.id)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

/** One waitlist entry: email, when they joined, and whether/when they've
 *  already been invited. Non-destructive, resendable — a plain ghost button,
 *  no confirm step and no Rust (this screen's single Rust use stays on the
 *  destructive user-delete confirm above). */
function WaitlistRow({
  entry,
  inviting,
  onInvite,
}: {
  entry: WaitlistEntry;
  inviting: boolean;
  onInvite: () => void;
}) {
  const joined = new Date(entry.created_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

  return (
    <div className="flex items-center justify-between gap-4">
      <span className="min-w-0">
        <span className="block truncate font-mono text-[13px] text-ink">{entry.email}</span>
        <span className="mt-0.5 block font-mono text-[11px] font-light text-muted">
          joined {joined}
          {entry.invited_at
            ? ` · invited ${new Date(entry.invited_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              })}`
            : null}
        </span>
      </span>
      <Button
        variant="ghost"
        type="button"
        onClick={onInvite}
        disabled={inviting}
        className="shrink-0"
      >
        {inviting ? "sending…" : entry.invited_at ? "resend" : "invite"}
      </Button>
    </div>
  );
}

/**
 * One search result. The destructive delete is gated behind a typed confirm:
 * the admin must type the user's exact email to arm it. The armed delete button
 * is the page's single Rust signal (the `link` Button variant renders in Rust).
 */
function AdminUserRow({
  user,
  deleting,
  onDelete,
}: {
  user: AdminUser;
  deleting: boolean;
  onDelete: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");

  const matches = typed.trim().toLowerCase() === user.email.toLowerCase();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-4">
        <span className="min-w-0">
          <span className="block truncate font-mono text-[13px] text-ink">{user.email}</span>
          <span className="mt-0.5 block font-mono text-[11px] font-light text-muted">
            {user.display_name || "—"}
          </span>
        </span>
        {!confirming ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="shrink-0 font-mono uppercase tracking-ui text-[11px] text-ink underline underline-offset-[3px] hover:text-sage"
          >
            delete
          </button>
        ) : null}
      </div>

      {confirming ? (
        <div className="space-y-3 border-l border-border pl-4">
          <p className="font-mono text-[11px] font-light text-muted">
            type the email to confirm. this can't be undone.
          </p>
          <TextField
            id={`admin-confirm-${user.id}`}
            label="confirm email"
            name="confirm-email"
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            disabled={deleting}
          />
          <div className="flex items-center gap-4">
            {/* The page's single Rust use: the armed destructive confirm. */}
            <Button variant="link" type="button" onClick={onDelete} disabled={!matches || deleting}>
              {deleting ? "deleting…" : "delete account"}
            </Button>
            <Button
              variant="ghost"
              type="button"
              onClick={() => {
                setConfirming(false);
                setTyped("");
              }}
              disabled={deleting}
            >
              cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
