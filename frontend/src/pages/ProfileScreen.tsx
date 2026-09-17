import { type FormEvent, useState } from "react";
import { PASSWORD_MIN_LENGTH, type Club } from "../services/api";
import type { PushPermissionStatus } from "../ios/push";
import { Button } from "../components/Button";
import { PaperSurface } from "../components/PaperSurface";
import { TextField } from "../components/TextField";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ClubName } from "../components/ClubName";
import { FormError } from "../components/FormError";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { ConcentricRings } from "../components/ConcentricRings";
import { CrownIcon } from "../components/CrownIcon";
import { UserAvatar } from "../components/avatars/UserAvatar";

export type NotificationPreferenceKey =
  | "email_notifications"
  | "push_lifecycle_enabled"
  | "push_deadline_reminders_enabled";

type ProfileScreenProps = {
  userId: string | null;
  displayName: string | null;
  email: string | null;
  archivedClubs: Club[];
  loading: boolean;
  error?: string | null;
  onOpenClub: (id: string) => void;
  onOpenSubmissionHistory: () => void;
  onSaveName: (name: string) => void;
  saving: boolean;
  saveError?: string | null;
  saved: boolean;
  hasPassword: boolean;
  onSetPassword: (password: string) => void;
  settingPassword: boolean;
  setPasswordError?: string | null;
  googleEnabled: boolean;
  googleLinked: boolean;
  onLinkGoogle: () => void;
  linkingGoogle: boolean;
  linkGoogleError?: string | null;
  /** Calm message from returning to /profile?google_link=<outcome> (the
   *  Google-link redirect's return leg) -- e.g. "google account linked." or an
   *  explanation for a denial/conflict. `isError` only changes whether it reads
   *  as a problem; it never takes the form-error color (ADR 0004 excludes a
   *  third-party outcome the user didn't do anything invalid to cause). */
  googleLinkNotice?: { message: string; isError: boolean } | null;
  /** null on web (section hides entirely) -- on native iOS, whatever the OS
   *  already knows about this device's permission (MysteryMixClub-4vii.27,
   *  IOS-04). Covers anyone who denied or dismissed the onboarding
   *  auto-prompt, or joined before it existed. */
  pushStatus?: PushPermissionStatus | null;
  onEnablePush?: () => void;
  enablingPush?: boolean;
  /** Whether push notifications exist on this platform at all (native iOS) --
   *  gates whether the two push preference toggles below render, same
   *  fail-safe-hide reasoning as `googleEnabled`/`pushStatus`. */
  pushAvailable?: boolean;
  /** null until the initial profile load resolves. */
  notificationPrefs?: Record<NotificationPreferenceKey, boolean> | null;
  onTogglePreference?: (key: NotificationPreferenceKey, value: boolean) => void;
  savingPref?: NotificationPreferenceKey | null;
  prefsError?: string | null;
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
 * Profile screen: edit display name, browse archived clubs, and manage account
 * (log out all devices, export data, delete account).
 *
 * The preferred-service picker was pulled on 2026-08-11 (Dawn) pending a
 * design. Display only: `preferred_service` still lives on the user, `useAuth`
 * still exposes it, and every platform-link ordering across the app still
 * honours whatever is already saved — there is simply no longer a way to
 * change it here. `updatePreferredService` in services/api.ts is kept for the
 * same reason; it is not dead code.
 *
 * Renders on the light `paper` surface (ADR 0013). Amber here. Placement is a
 * design decision (ADR 0012), and this screen leans on it more than most: the
 * section headings are all amber — `ink-accent`, the paper-legal value, since
 * `accent` is 2.62:1 on white — and the cassette avatar is drawn in it because
 * it is the *viewer's own*. That last point is the
 * line worth holding — `ClubHomeScreen`'s member roster passes no `accent`, so
 * amber on a person keeps meaning "you", the same rule the `/home` display-name
 * eyebrow follows.
 *
 * Two things still deliberately decline it:
 *  - The archived clubs list carries NO amber. It is the same `GET /clubs` data
 *    R8 renders, filtered to `complete` — an unbounded, monotonically growing
 *    set with no pagination and no way to hide a club — so a per-card accent bar
 *    would render a column of amber, which is amber as pattern. That is the one
 *    constraint ADR 0012 kept. Completion is carried instead by the "archived"
 *    grouping, a `muted-foreground` crown glyph, and the state Badge already
 *    reading "complete". Those cards are dark islands on the light page and
 *    keep the dark ramp throughout (the frame model).
 *  - Delete-account is irreversible and takes `Button variant="destructive"`,
 *    never the amber `link` variant. See DeleteAccountSection. The three
 *    recoverable account actions (log out everywhere, export data, arm/cancel
 *    the delete confirm) stay `ghost`, matching R10's split between delete-club
 *    and leave-club.
 *
 * The shared TopNav is rendered by AuthedLayout, so this is content-only and
 * this screen renders no disc mark of its own.
 */
export function ProfileScreen({
  userId,
  displayName,
  email,
  archivedClubs,
  loading,
  error,
  onOpenClub,
  onOpenSubmissionHistory,
  onSaveName,
  saving,
  saveError,
  saved,
  hasPassword,
  onSetPassword,
  settingPassword,
  setPasswordError,
  googleEnabled,
  googleLinked,
  onLinkGoogle,
  linkingGoogle,
  linkGoogleError,
  googleLinkNotice,
  pushStatus,
  onEnablePush,
  enablingPush = false,
  pushAvailable = false,
  notificationPrefs,
  onTogglePreference,
  savingPref,
  prefsError,
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
      <PaperSurface nested>
        <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
          <ConcentricRings size={88} spinning onPaper className="mx-auto" />
        </main>
      </PaperSurface>
    );
  }

  return (
    // Light surface (ADR 0013), `nested` because AuthedLayout owns the shell.
    <PaperSurface nested>
      <main className="mx-auto w-full max-w-lg px-4 pt-8 pb-16 sm:px-8">
        <div className="flex items-center gap-4">
          {/* Amber because this is the viewer's own avatar — the roster on
              ClubHomeScreen deliberately stays neutral. `onPaper` inverts the
              chip: white fill, near-black ring, `ink-accent` cassette. */}
          {userId ? <UserAvatar userId={userId} size={56} accent onPaper /> : null}
          <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
            profile
          </h1>
        </div>

        {error ? (
          // A failed *load*, not a form error: the profile never resolved, so
          // this replaces the screen's content rather than describing a field.
          // ADR 0004's error category is form validation only, so this stays
          // ordinary body copy — `ink`, this page's primary text.
          <p role="alert" className="mt-6 text-sm leading-[1.72] text-ink">
            {error}
          </p>
        ) : (
          <div className="mt-8">
            {email ? (
              <section className="mb-12">
                <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
                  email
                </h2>
                {/* Mono at normal tracking is the system's signature for a value. */}
                <p className="mt-2 font-mono text-sm text-ink">{email}</p>
              </section>
            ) : null}

            <NameForm
              displayName={displayName}
              onSaveName={onSaveName}
              saving={saving}
              saveError={saveError}
              saved={saved}
            />

            <section className="mt-12 border-t border-ink-hairline pt-10">
              <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
                your submissions
              </h2>
              <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
                every song you&apos;ve ever submitted, across every club.
              </p>
              <div className="mt-4">
                <Button onPaper variant="ghost" type="button" onClick={onOpenSubmissionHistory}>
                  view history
                </Button>
              </div>
            </section>

            <ArchivedClubs clubs={archivedClubs} onOpenClub={onOpenClub} />

            <AccountSettingsSection
              hasPassword={hasPassword}
              onSetPassword={onSetPassword}
              settingPassword={settingPassword}
              setPasswordError={setPasswordError}
              googleEnabled={googleEnabled}
              googleLinked={googleLinked}
              onLinkGoogle={onLinkGoogle}
              linkingGoogle={linkingGoogle}
              linkGoogleError={linkGoogleError}
              googleLinkNotice={googleLinkNotice}
            />

            {notificationPrefs ? (
              <NotificationPreferencesSection
                prefs={notificationPrefs}
                onTogglePreference={onTogglePreference}
                savingPref={savingPref}
                prefsError={prefsError}
                pushAvailable={pushAvailable}
                pushStatus={pushStatus}
                onEnablePush={onEnablePush}
                enablingPush={enablingPush}
              />
            ) : null}

            <section className="mt-12 border-t border-ink-hairline pt-10">
              <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
                security
              </h2>
              <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
                signs you out on every device and browser.
              </p>
              {/* Recoverable — you sign back in. `ghost`, not `destructive`. */}
              <div className="mt-4">
                <Button onPaper variant="ghost" onClick={onLogoutAll} disabled={logoutAllBusy}>
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
    </PaperSurface>
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
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        display name
      </h2>
      <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-6">
        {/* `invalid` rather than TextField's own `error` prop: the message is
            rendered by this form (it always was) and keeps its own id, and
            `invalid` emits exactly the `aria-invalid` this field carried
            before while also turning the underline `ink-destructive`. */}
        <TextField
          onPaper
          id="profile-display-name"
          label="name"
          name="display-name"
          autoComplete="nickname"
          placeholder="what should we call you?"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={saving}
          invalid={Boolean(saveError)}
          aria-describedby={saveError ? "profile-display-name-error" : undefined}
        />
        {saveError ? (
          <FormError onPaper id="profile-display-name-error">
            {saveError}
          </FormError>
        ) : null}
        <div className="flex items-center gap-4">
          <Button onPaper type="submit" disabled={saving}>
            {saving ? "saving…" : "save"}
          </Button>
          {saved ? (
            <span className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">
              saved
            </span>
          ) : null}
        </div>
      </form>
    </section>
  );
}

/**
 * The archived (completed) clubs, on R8's list-card pattern: a `card` surface
 * with the pure-CSS hover lift, a mono eyebrow, a `font-display` uppercase item
 * title, and a mono meta row.
 *
 * **No amber here, on any card.** R8 settled this for the same data: `GET
 * /clubs` is unbounded and only grows, a completed club stays completed
 * forever, and nothing lets a user hide one — so the accent bar the retired
 * system put on the most-recently-completed card would, on a long-lived
 * account, sit at the top of a column that keeps growing beneath it. Amber's
 * category covers achievement, but not as a per-row pattern. The crown glyph
 * is `muted-foreground` and the state Badge stays `default`.
 */
function ArchivedClubs({ clubs, onOpenClub }: { clubs: Club[]; onOpenClub: (id: string) => void }) {
  return (
    <section className="mt-12">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        archived ({clubs.length})
      </h2>
      {clubs.length === 0 ? (
        <p className="mt-4 text-sm leading-[1.72] text-ink-muted">no completed clubs yet</p>
      ) : (
        <ul className="mt-4 space-y-4">
          {clubs.map((club) => (
            <li key={club.id}>
              <Card className="transition-[box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:shadow-z3">
                <button
                  type="button"
                  onClick={() => onOpenClub(club.id)}
                  className="block w-full text-left"
                >
                  {/* Inside a `Card`, so this keeps the DARK ramp — the frame
                      model: a card is its own surface and never mixes the two
                      (ADR 0013). `ink-muted` here would be the light page's
                      grey on near-black. */}
                  <span className="flex items-center gap-1.5 font-mono text-mini uppercase tracking-mono-caps text-muted-foreground">
                    <CrownIcon className="text-muted-foreground" />
                    club
                  </span>
                  <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
                    <ClubName name={club.name} />
                  </h3>
                  <div className="mt-4 flex items-center justify-between">
                    <span className="font-mono text-meta text-muted-foreground">
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

/**
 * Set-a-password / link-Google (MysteryMixClub-ali8.6, ADR 0007). Two
 * independent sub-parts, each keyed off its own already-persisted flag
 * (`hasPassword` / `googleLinked`) so a completed action swaps its form for a
 * plain status line rather than staying interactive.
 *
 * A failed save or a failed link-start is a form error and takes `FormError`
 * (ADR 0004 — its own color category, and several may show at once). The
 * google-redirect *outcome* notice does not: a third-party sign-in being
 * denied or cancelled is explicitly outside that category, so it stays
 * ordinary body copy.
 */
function AccountSettingsSection({
  hasPassword,
  onSetPassword,
  settingPassword,
  setPasswordError,
  googleEnabled,
  googleLinked,
  onLinkGoogle,
  linkingGoogle,
  linkGoogleError,
  googleLinkNotice,
}: {
  hasPassword: boolean;
  onSetPassword: (password: string) => void;
  settingPassword: boolean;
  setPasswordError?: string | null;
  googleEnabled: boolean;
  googleLinked: boolean;
  onLinkGoogle: () => void;
  linkingGoogle: boolean;
  linkGoogleError?: string | null;
  googleLinkNotice?: { message: string; isError: boolean } | null;
}) {
  return (
    <section className="mt-12 border-t border-ink-hairline pt-10">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        account settings
      </h2>

      <div className="mt-4">
        <SetPasswordForm
          hasPassword={hasPassword}
          onSetPassword={onSetPassword}
          saving={settingPassword}
          saveError={setPasswordError}
        />
      </div>

      {googleEnabled ? (
        <div className="mt-8">
          <p className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">
            google account
          </p>

          {googleLinkNotice ? (
            <p
              role={googleLinkNotice.isError ? "alert" : "status"}
              className={[
                "mt-2 text-sm leading-[1.72]",
                googleLinkNotice.isError ? "text-ink" : "text-ink-muted",
              ].join(" ")}
            >
              {googleLinkNotice.message}
            </p>
          ) : null}

          {googleLinked ? (
            <p className="mt-2 font-mono text-sm text-ink-muted">linked</p>
          ) : (
            <div className="mt-3">
              <Button
                onPaper
                variant="ghost"
                type="button"
                onClick={onLinkGoogle}
                disabled={linkingGoogle}
              >
                {linkingGoogle ? "connecting…" : "link google account"}
              </Button>
              {linkGoogleError ? (
                <div className="mt-3">
                  <FormError onPaper>{linkGoogleError}</FormError>
                </div>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Notifications: email + the two push preference toggles, plus -- when push
 * exists on this platform at all (native iOS) -- the OS permission status
 * and enable action, in the SAME section as the toggles it gates.
 *
 * MysteryMixClub-4vii.31 folded a separate "notifications" section (holding
 * only the permission button) into this one after a real device test showed
 * exactly the confusion two similarly-worded, separately-titled sections
 * invites: toggling "push: updates" here does nothing to iOS permission by
 * itself (it only PATCHes an account preference) and was easy to mistake for
 * "the" way to enable push, since the two sections described themselves in
 * nearly the same words. Now there is one place on the page for push, with
 * the permission step ordered first -- it's the thing that has to happen
 * before the toggles below it can matter at all.
 *
 * Email (MysteryMixClub-4vii.28): the `email_notifications` backend field
 * has existed since email notifications shipped, but this is the first
 * frontend control for it -- until now, unsubscribing meant the email's own
 * unsubscribe link. Every toggle here saves independently and immediately on
 * click (no separate "save" step, unlike the name/password forms above) --
 * optimistic in the container, so a failed save reverts the checkbox and
 * surfaces `prefsError` rather than leaving a stale, unsent state checked.
 *
 * The two push toggles, and the permission block above them, only render
 * when push exists on this platform at all -- same fail-safe-hide reasoning
 * as `googleEnabled`: a toggle (or a permission button) for a channel that
 * can never deliver on this platform is confusing UI, not a neutral no-op.
 */
function NotificationPreferencesSection({
  prefs,
  onTogglePreference,
  savingPref,
  prefsError,
  pushAvailable,
  pushStatus,
  onEnablePush,
  enablingPush = false,
}: {
  prefs: Record<NotificationPreferenceKey, boolean>;
  onTogglePreference?: (key: NotificationPreferenceKey, value: boolean) => void;
  savingPref?: NotificationPreferenceKey | null;
  prefsError?: string | null;
  pushAvailable: boolean;
  pushStatus?: PushPermissionStatus | null;
  onEnablePush?: () => void;
  enablingPush?: boolean;
}) {
  return (
    <section className="mt-12 border-t border-ink-hairline pt-10">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        notifications
      </h2>

      {pushAvailable && pushStatus ? (
        <div className="mt-4">
          {pushStatus === "granted" ? (
            <p className="font-mono text-sm text-ink-muted">push is on for this device</p>
          ) : pushStatus === "denied" ? (
            <p className="text-sm leading-[1.72] text-ink-muted">
              push is off at the iOS level, so the push toggles below won&apos;t do anything
              until you turn it back on in iOS settings &gt; notifications &gt; mysterymixclub.
            </p>
          ) : (
            <>
              <p className="text-sm leading-[1.72] text-ink-muted">
                turn on push to get these on your phone&apos;s lock screen, not just by email.
              </p>
              <div className="mt-3">
                <Button
                  onPaper
                  variant="ghost"
                  type="button"
                  onClick={onEnablePush}
                  disabled={enablingPush}
                >
                  {enablingPush ? "enabling…" : "turn on push notifications"}
                </Button>
              </div>
            </>
          )}
        </div>
      ) : null}

      <div className="mt-6 space-y-5">
        <PreferenceCheckbox
          id="pref-email-notifications"
          label="email"
          description="submission and voting reminders, and mix updates, by email."
          checked={prefs.email_notifications}
          disabled={Boolean(savingPref)}
          onChange={(checked) => onTogglePreference?.("email_notifications", checked)}
        />
        {pushAvailable ? (
          <>
            <PreferenceCheckbox
              id="pref-push-lifecycle"
              label="push: updates"
              description="a nudge when it's your turn to submit or vote, and when a mystery mix wraps up."
              checked={prefs.push_lifecycle_enabled}
              disabled={Boolean(savingPref)}
              onChange={(checked) => onTogglePreference?.("push_lifecycle_enabled", checked)}
            />
            <PreferenceCheckbox
              id="pref-push-deadline-reminders"
              label="push: reminders"
              description="an extra nudge as a submission or voting deadline approaches."
              checked={prefs.push_deadline_reminders_enabled}
              disabled={Boolean(savingPref)}
              onChange={(checked) =>
                onTogglePreference?.("push_deadline_reminders_enabled", checked)
              }
            />
          </>
        ) : null}
      </div>
      {prefsError ? (
        <div className="mt-3">
          <FormError onPaper>{prefsError}</FormError>
        </div>
      ) : null}
    </section>
  );
}

function PreferenceCheckbox({
  id,
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex cursor-pointer items-start gap-3">
      {/* Same drawn-checkbox construction as OnboardingScreen's consent box,
          re-solved for the paper surface: `ink-accent` fill (checked) instead
          of `accent`, `paper` (white) mark instead of `accent-foreground` --
          `ink-accent` is dark enough on white that a white mark clears the
          3:1 non-text floor. */}
      <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
          className="peer col-start-1 row-start-1 h-4 w-4 cursor-pointer appearance-none rounded-hair border border-ink-muted bg-transparent transition-colors duration-150 checked:border-ink-accent checked:bg-ink-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink-accent focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:cursor-not-allowed disabled:opacity-60"
        />
        <CheckmarkIcon className="pointer-events-none col-start-1 row-start-1 hidden text-paper peer-checked:block" />
      </span>
      <span>
        <span className="block font-mono text-mini uppercase tracking-mono-caps text-ink">
          {label}
        </span>
        <span className="mt-1 block text-meta leading-[1.6] text-ink-muted">{description}</span>
      </span>
    </label>
  );
}

function SetPasswordForm({
  hasPassword,
  onSetPassword,
  saving,
  saveError,
}: {
  hasPassword: boolean;
  onSetPassword: (password: string) => void;
  saving: boolean;
  saveError?: string | null;
}) {
  const [password, setPassword] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password) return;
    onSetPassword(password);
  }

  if (hasPassword) {
    return (
      <>
        <p className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">password</p>
        <p className="mt-2 font-mono text-sm text-ink-muted">password set</p>
      </>
    );
  }

  return (
    <>
      <p className="font-mono text-mini uppercase tracking-mono-caps text-ink-muted">password</p>
      <p className="mt-1 text-sm leading-[1.72] text-ink-muted">
        add a password so you can sign in without a magic link.
      </p>
      <form onSubmit={handleSubmit} noValidate className="mt-4 space-y-3">
        <div>
          <TextField
            onPaper
            id="profile-set-password"
            label="new password"
            type="password"
            name="new-password"
            autoComplete="new-password"
            revealToggle
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={saving}
            aria-describedby={
              saveError ? "profile-set-password-error" : "profile-set-password-hint"
            }
          />
          {saveError ? (
            <div className="mt-2">
              <FormError onPaper id="profile-set-password-error">
                {saveError}
              </FormError>
            </div>
          ) : (
            <p
              id="profile-set-password-hint"
              className="mt-2 text-meta leading-[1.6] text-ink-muted"
            >
              {PASSWORD_MIN_LENGTH} characters or more.
            </p>
          )}
        </div>
        <div>
          <Button onPaper type="submit" disabled={saving || !password}>
            {saving ? "saving…" : "set password"}
          </Button>
        </div>
      </form>
    </>
  );
}

/** Downloading your own data changes nothing and can be repeated, so the
 *  control is `ghost`. A failed export is a form error (ADR 0004). */
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
    <section className="mt-12 border-t border-ink-hairline pt-10">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        your data
      </h2>
      <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
        download a copy of everything tied to your account: profile, submissions, votes, and notes.
      </p>
      <p className="mt-2 text-sm leading-[1.72] text-ink-muted">
        we provide this to meet gdpr's right of access (article 15) and data portability (article
        20).
      </p>
      <div className="mt-4">
        <Button
          onPaper
          variant="ghost"
          type="button"
          onClick={onExportData}
          disabled={exportingData}
        >
          {exportingData ? "preparing…" : "download my data"}
        </Button>
      </div>
      {exportDataError ? (
        <div className="mt-3">
          <FormError onPaper>{exportDataError}</FormError>
        </div>
      ) : null}
    </section>
  );
}

/**
 * The most destructive action in the app, on R10's two-step confirm pattern:
 * the first control arms the confirm, the second commits, and the arming step
 * is unchanged in every respect.
 *
 * The commit takes `Button variant="destructive"` (R2). Deleting an account is
 * irreversible — it takes every club membership, submission, vote and note with
 * it and there is no restore — so it reads as danger rather than as an ordinary
 * amber action. The arming control and the cancel stay `ghost`, exactly as R10
 * kept the recoverable leave-club on `ghost`: only the irreversible commit gets
 * the red fill, or the section becomes one undifferentiated danger zone.
 */
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
    <section className="mt-12 border-t border-ink-hairline pt-10">
      <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-accent">
        delete account
      </h2>
      {!confirming ? (
        <div className="mt-4">
          <Button onPaper variant="ghost" type="button" onClick={() => setConfirming(true)}>
            delete my account
          </Button>
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <p className="text-sm leading-[1.72] text-ink-muted">
            this permanently deletes your account and all your data. are you sure?
          </p>
          <div className="flex items-center gap-4">
            <Button
              onPaper
              variant="destructive"
              type="button"
              onClick={onDeleteAccount}
              disabled={deletingAccount}
            >
              {deletingAccount ? "deleting…" : "yes, delete my account"}
            </Button>
            <Button
              onPaper
              variant="ghost"
              type="button"
              onClick={() => setConfirming(false)}
              disabled={deletingAccount}
            >
              cancel
            </Button>
          </div>
        </div>
      )}
      {deleteAccountError ? (
        <div className="mt-3">
          <FormError onPaper>{deleteAccountError}</FormError>
        </div>
      ) : null}
    </section>
  );
}
