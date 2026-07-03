import { type FormEvent, useState } from "react";
import type { AdminSpotifyRound, AdminUser } from "../services/api";
import { Badge } from "../components/Badge";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";

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
  spotifyRounds: AdminSpotifyRound[];
  spotifyLoading: boolean;
  spotifyError?: string | null;
  onGenerateSpotifyPlaylist: (roundId: string) => void;
  generatingRoundId: string | null;
};

/**
 * Thin platform-admin page: search users by email, then hard-delete a match
 * behind a typed confirm; and generate/refresh a round's Spotify playlist
 * (MYS-169 — the only role allowed to, since the shared account is a real
 * person's own Spotify login). Content-only — the shared TopNav is rendered by
 * AuthedLayout. The single Rust signal on this screen is the destructive confirm
 * action; everything else, including the Spotify section, stays in the
 * Sage/Ink family. Underline-only inputs, ALL-CAPS labels, calm lowercase copy.
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
  spotifyRounds,
  spotifyLoading,
  spotifyError,
  onGenerateSpotifyPlaylist,
  generatingRoundId,
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
          <h2 className="font-serif lowercase text-[20px] leading-tight text-ink">
            spotify playlists
          </h2>
          <p className="mt-2 font-mono text-[13px] font-light text-muted">
            generate or refresh a round&apos;s public playlist. every live round with
            submissions, across every league.
          </p>

          {spotifyError ? (
            <p role="alert" className="mt-4 font-mono text-[11px] text-ink">
              {spotifyError}
            </p>
          ) : null}

          <div className="mt-6">
            {spotifyLoading ? (
              <p className="font-mono text-[13px] font-light text-muted">loading…</p>
            ) : spotifyRounds.length === 0 ? (
              <p className="font-mono text-[13px] font-light text-muted">no rounds ready</p>
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {spotifyRounds.map((round) => (
                  <li key={round.round_id} className="py-4">
                    <SpotifyRoundRow
                      round={round}
                      generating={generatingRoundId === round.round_id}
                      onGenerate={() => onGenerateSpotifyPlaylist(round.round_id)}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
    </main>
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
            <Button
              variant="link"
              type="button"
              onClick={onDelete}
              disabled={!matches || deleting}
            >
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

/**
 * One round on the Spotify generate/regenerate list. Shows the league, round
 * label, plain-text state + submission count, an "open" link if a playlist
 * already exists, and the generate/regenerate action. No Rust here — this
 * screen's single Rust use is the destructive delete confirm above.
 */
function SpotifyRoundRow({
  round,
  generating,
  onGenerate,
}: {
  round: AdminSpotifyRound;
  generating: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="min-w-0">
        <span className="block truncate font-mono text-[13px] text-ink">
          {round.league_name} — {round.round_label}
        </span>
        <span className="mt-1 flex items-center gap-2">
          <Badge>{round.state}</Badge>
          <span className="font-mono text-[11px] font-light text-muted">
            {round.submission_count} submission{round.submission_count === 1 ? "" : "s"}
          </span>
        </span>
      </span>
      <div className="flex shrink-0 items-center gap-4">
        {round.playlist_url ? (
          <a
            href={round.playlist_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] hover:text-ink"
          >
            open
          </a>
        ) : null}
        <Button variant="ghost" type="button" onClick={onGenerate} disabled={generating}>
          {generating ? "generating…" : round.playlist_url ? "regenerate" : "generate"}
        </Button>
      </div>
    </div>
  );
}
