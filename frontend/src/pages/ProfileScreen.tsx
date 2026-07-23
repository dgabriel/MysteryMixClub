import { type FormEvent, useState } from "react";
import type { Club } from "../services/api";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { UserAvatar } from "../components/avatars/UserAvatar";
import { HelpLink } from "../components/HelpLink";

type ProfileScreenProps = {
  userId: string | null;
  displayName: string | null;
  email: string | null;
  preferredService: "spotify" | "youtube" | "deezer" | null;
  archivedClubs: Club[];
  loading: boolean;
  error?: string | null;
  onOpenClub: (id: string) => void;
  onSaveName: (name: string) => void;
  saving: boolean;
  saveError?: string | null;
  saved: boolean;
  onSavePreferredService: (service: "spotify" | "youtube" | "deezer" | null) => void;
  savingService: boolean;
  saveServiceError?: string | null;
  savedService: boolean;
  onLogoutAll: () => void;
  logoutAllBusy?: boolean;
  onExportData: () => void;
  exportingData: boolean;
  exportDataError?: string | null;
  onDeleteAccount: () => void;
  deletingAccount: boolean;
  deleteAccountError?: string | null;
};

/**
 * Profile screen: edit display name, preferred service, browse archived clubs,
 * and manage account (log out all devices, delete account).
 *
 * Rust budget: the single Rust use is the accent bar on the most-recently-completed
 * archived club card. The delete-account confirm uses ghost/ink styling only.
 */
export function ProfileScreen({
  userId,
  displayName,
  email,
  preferredService,
  archivedClubs,
  loading,
  error,
  onOpenClub,
  onSaveName,
  saving,
  saveError,
  saved,
  onSavePreferredService,
  savingService,
  saveServiceError,
  savedService,
  onLogoutAll,
  logoutAllBusy = false,
  onExportData,
  exportingData,
  exportDataError,
  onDeleteAccount,
  deletingAccount,
  deleteAccountError,
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
      <div className="flex items-center gap-5">
        {userId ? <UserAvatar userId={userId} size={56} /> : null}
        <h1 className="font-serif lowercase text-[28px] leading-tight text-ink">profile</h1>
      </div>

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

          <PreferredServicePicker
            current={preferredService}
            onSave={onSavePreferredService}
            saving={savingService}
            saveError={saveServiceError}
            saved={savedService}
          />

          <ArchivedClubs clubs={archivedClubs} onOpenClub={onOpenClub} />

          <section className="mt-12 border-t border-border pt-10">
            <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">security</h2>
            <p className="mt-2 font-mono text-[13px] font-light text-muted">
              signs you out on every device and browser.
            </p>
            <div className="mt-4">
              <Button variant="ghost" onClick={onLogoutAll} disabled={logoutAllBusy}>
                {logoutAllBusy ? "signing out…" : "log out of all devices"}
              </Button>
            </div>
          </section>

          <ExportDataSection
            onExportData={onExportData}
            exportingData={exportingData}
            exportDataError={exportDataError}
          />

          <DeleteAccountSection
            onDeleteAccount={onDeleteAccount}
            deletingAccount={deletingAccount}
            deleteAccountError={deleteAccountError}
          />
        </div>
      )}
    </main>
  );
}

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
      <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-6">
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
          aria-describedby={saveError ? "profile-display-name-error" : undefined}
        />
        {saveError ? (
          <p id="profile-display-name-error" role="alert" className="font-mono text-[13px] text-ink">
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

const SERVICES = [
  { value: "spotify", label: "spotify" },
  { value: "youtube", label: "youtube" },
  { value: "deezer", label: "deezer" },
  { value: null, label: "none" },
] as const;

function PreferredServicePicker({
  current,
  onSave,
  saving,
  saveError,
  saved,
}: {
  current: "spotify" | "youtube" | "deezer" | null;
  onSave: (service: "spotify" | "youtube" | "deezer" | null) => void;
  saving: boolean;
  saveError?: string | null;
  saved: boolean;
}) {
  return (
    <section className="mt-12">
      <span className="flex items-center gap-2">
        <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
          preferred service
        </h2>
        <HelpLink anchor="listening-playlists" />
      </span>
      <p className="mt-1 font-mono text-[13px] font-light text-muted">
        platform links show this service first.
      </p>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2">
        {SERVICES.map(({ value, label }) => {
          const isActive = current === value;
          return (
            <button
              key={label}
              type="button"
              disabled={saving || isActive}
              onClick={() => onSave(value)}
              className={[
                "py-1.5 font-mono uppercase tracking-ui text-[11px] transition-colors duration-150",
                isActive
                  ? "text-ink underline underline-offset-[3px] cursor-default"
                  : "text-muted hover:text-ink disabled:opacity-50",
              ].join(" ")}
            >
              {label}
            </button>
          );
        })}
        {saved ? (
          <span className="font-mono text-[11px] font-light text-muted">saved</span>
        ) : null}
      </div>
      {saveError ? (
        <p role="alert" className="mt-2 font-mono text-[13px] text-ink">
          {saveError}
        </p>
      ) : null}
    </section>
  );
}

function ArchivedClubs({
  clubs,
  onOpenClub,
}: {
  clubs: Club[];
  onOpenClub: (id: string) => void;
}) {
  return (
    <section className="mt-12">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        archived ({clubs.length})
      </h2>
      {clubs.length === 0 ? (
        <p className="mt-4 font-mono text-[13px] font-light text-muted">no completed clubs yet</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {clubs.map((club, index) => (
            <li key={club.id}>
              {/* The screen's single Rust use: accent bar on the most-recently
                  completed club only (index 0). */}
              <Card
                accent={index === 0}
                className="group transition-colors duration-150 hover:bg-sage-pale"
              >
                <button
                  type="button"
                  onClick={() => onOpenClub(club.id)}
                  className="block w-full text-left"
                >
                  <span className="font-mono uppercase tracking-label text-[9px] text-muted group-hover:text-sage">
                    club
                  </span>
                  <h3 className="mt-1 font-serif text-[20px] leading-tight text-ink">
                    {club.name}
                  </h3>
                  <div className="mt-3 flex items-center justify-between">
                    <span className="font-mono text-[11px] font-light text-muted group-hover:text-sage">
                      {club.total_mixes} mixes
                    </span>
                    <Badge>{club.state}</Badge>
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

function ExportDataSection({
  onExportData,
  exportingData,
  exportDataError,
}: {
  onExportData: () => void;
  exportingData: boolean;
  exportDataError?: string | null;
}) {
  return (
    <section className="mt-12 border-t border-border pt-10">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">your data</h2>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        download a copy of everything tied to your account: profile, submissions, votes, and
        notes.
      </p>
      <p className="mt-2 font-mono text-[13px] font-light text-muted">
        we provide this to meet gdpr's right of access (article 15) and data portability (article
        20).
      </p>
      <div className="mt-4">
        <Button variant="ghost" type="button" onClick={onExportData} disabled={exportingData}>
          {exportingData ? "preparing…" : "download my data"}
        </Button>
      </div>
      {exportDataError ? (
        <p role="alert" className="mt-3 font-mono text-[13px] text-ink">
          {exportDataError}
        </p>
      ) : null}
    </section>
  );
}

function DeleteAccountSection({
  onDeleteAccount,
  deletingAccount,
  deleteAccountError,
}: {
  onDeleteAccount: () => void;
  deletingAccount: boolean;
  deleteAccountError?: string | null;
}) {
  const [confirming, setConfirming] = useState(false);

  return (
    <section className="mt-12 border-t border-border pt-10">
      <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
        delete account
      </h2>
      {!confirming ? (
        <div className="mt-4">
          <Button variant="ghost" type="button" onClick={() => setConfirming(true)}>
            delete my account
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <p className="font-mono text-[13px] font-light text-ink">
            this permanently deletes your account and all your data. are you sure?
          </p>
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              type="button"
              onClick={onDeleteAccount}
              disabled={deletingAccount}
            >
              {deletingAccount ? "deleting…" : "yes, delete my account"}
            </Button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deletingAccount}
              className="py-1.5 font-mono uppercase tracking-ui text-[11px] text-muted hover:text-ink disabled:opacity-50"
            >
              cancel
            </button>
          </div>
        </div>
      )}
      {deleteAccountError ? (
        <p role="alert" className="mt-3 font-mono text-[13px] text-ink">
          {deleteAccountError}
        </p>
      ) : null}
    </section>
  );
}
