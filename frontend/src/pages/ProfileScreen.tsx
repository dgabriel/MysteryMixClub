import { type FormEvent, useState } from "react";
import type { League } from "../services/api";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";

type ProfileScreenProps = {
  displayName: string | null;
  /** The user's account email — read-only identity, shown above the name editor. */
  email: string | null;
  /** Completed leagues, most-recently-completed first. Linkable to the league home. */
  archivedLeagues: League[];
  loading: boolean;
  error?: string | null;
  onOpenLeague: (id: string) => void;
  onSaveName: (name: string) => void;
  saving: boolean;
  saveError?: string | null;
  /** Brief "saved" acknowledgement after a successful name change. */
  saved: boolean;
  onLogoutAll: () => void;
  logoutAllBusy?: boolean;
};

/**
 * Profile screen: edit the display name and browse archived (completed) leagues.
 * Content-only — the shared TopNav is rendered by AuthedLayout. The single Rust
 * signal on this screen is the left accent bar on the most-recently-completed
 * league card; everything else stays in the Sage/Ink family. Underline-only
 * input, ALL-CAPS labels, calm copy.
 */
export function ProfileScreen({
  displayName,
  email,
  archivedLeagues,
  loading,
  error,
  onOpenLeague,
  onSaveName,
  saving,
  saveError,
  saved,
  onLogoutAll,
  logoutAllBusy = false,
}: ProfileScreenProps) {
  if (loading) {
    return (
      <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
        <ConcentricRings size={88} spinning className="mx-auto" />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-lg px-4 pb-16 sm:px-8">
      <h1 className="font-serif lowercase text-[28px] leading-tight text-ink">profile</h1>
      {error ? (
        <p role="alert" className="mt-6 font-mono text-[13px] font-light text-muted">
          {error}
        </p>
      ) : (
        <div className="mt-8">
          {email ? (
            <section className="mb-12">
              <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">email</h2>
              <p className="mt-2 font-mono text-[13px] font-light text-ink">{email}</p>
            </section>
          ) : null}

          <NameForm
            displayName={displayName}
            onSaveName={onSaveName}
            saving={saving}
            saveError={saveError}
            saved={saved}
          />

          <ArchivedLeagues leagues={archivedLeagues} onOpenLeague={onOpenLeague} />

          <section className="mt-12 border-t border-border pt-10">
            <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">security</h2>
            <p className="mt-2 font-mono text-[11px] font-light text-muted">
              signs you out on every device and browser.
            </p>
            <div className="mt-4">
              <Button
                variant="ghost"
                onClick={onLogoutAll}
                disabled={logoutAllBusy}
              >
                {logoutAllBusy ? "signing out…" : "log out of all devices"}
              </Button>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

/**
 * Display-name editor. Seeds from the current name; saves only when it changed
 * and is non-empty. No Rust — this screen's single Rust use is the archived-league
 * accent below.
 */
function NameForm({
  displayName,
  onSaveName,
  saving,
  saveError,
  saved,
}: {
  displayName: string | null;
  onSaveName: (name: string) => void;
  saving: boolean;
  saveError?: string | null;
  saved: boolean;
}) {
  const [name, setName] = useState(displayName ?? "");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || trimmed === (displayName ?? "")) return;
    onSaveName(trimmed);
  }

  return (
    <section>
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">display name</h2>
      <form onSubmit={handleSubmit} className="mt-4 space-y-6">
        <TextField
          id="profile-display-name"
          label="name"
          name="display-name"
          autoComplete="nickname"
          placeholder="what should we call you?"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={saving}
          aria-invalid={saveError ? true : undefined}
        />

        {saveError ? (
          <p role="alert" className="font-mono text-[11px] text-ink">
            {saveError}
          </p>
        ) : null}

        <div className="flex items-center gap-4">
          <Button type="submit" disabled={saving}>
            {saving ? "saving…" : "save"}
          </Button>
          {saved ? (
            <span className="font-mono text-[11px] font-light text-muted">saved</span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

/**
 * Archived (completed) leagues, linkable to each league home. The most-recent
 * one carries the screen's single Rust accent bar; the rest are plain cards. An
 * empty archive shows a calm note.
 */
function ArchivedLeagues({
  leagues,
  onOpenLeague,
}: {
  leagues: League[];
  onOpenLeague: (id: string) => void;
}) {
  return (
    <section className="mt-12">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        archived ({leagues.length})
      </h2>

      {leagues.length === 0 ? (
        <p className="mt-4 font-mono text-[13px] font-light text-muted">no completed leagues yet</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {leagues.map((league, index) => (
            <li key={league.id}>
              {/* The screen's single Rust use: an accent bar on the most-recently
                  completed league only (index 0); the rest stay plain. */}
              <Card
                accent={index === 0}
                className="transition-colors duration-150 hover:bg-sage-pale"
              >
                <button
                  type="button"
                  onClick={() => onOpenLeague(league.id)}
                  className="block w-full text-left"
                >
                  <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                    league
                  </span>
                  <h3 className="mt-1 font-serif text-[20px] leading-tight text-ink">
                    {league.name}
                  </h3>
                  <div className="mt-3 flex items-center justify-between">
                    <span className="font-mono text-[11px] font-light text-muted">
                      {league.total_rounds} rounds
                    </span>
                    <Badge>{league.state}</Badge>
                  </div>
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
