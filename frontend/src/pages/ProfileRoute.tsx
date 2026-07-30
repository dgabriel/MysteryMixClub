import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ProfileScreen } from "./ProfileScreen";
import {
  ApiError,
  deleteAccount,
  exportMyData,
  getClubs,
  getGoogleEnabled,
  getMe,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  setPassword as apiSetPassword,
  startGoogleLink,
  updateDisplayName,
  updatePreferredService,
  type Club,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

/** Calm copy for the outcome flag Google's link callback redirects back with
 *  (?google_link=<outcome>, MysteryMixClub-ali8.6). `isError` only changes
 *  whether the message reads as a problem -- it never renders in Rust, per the
 *  style guide's carve-out for a third-party outcome the user didn't do
 *  anything invalid to cause (ADR 0004). */
function googleLinkOutcomeCopy(outcome: string): { message: string; isError: boolean } {
  switch (outcome) {
    case "linked":
      return { message: "google account linked.", isError: false };
    case "already_linked_elsewhere":
      return {
        message: "that google account is already linked to a different mysterymixclub account.",
        isError: true,
      };
    case "denied":
      return { message: "google sign-in was cancelled.", isError: true };
    case "invalid_state":
      return { message: "that link expired. try linking again.", isError: true };
    case "exchange_failed":
      return { message: "that didn't work. try again.", isError: true };
    case "email_unverified":
      return { message: "verify your email with google, then try again.", isError: true };
    case "error":
    default:
      return { message: "that didn't work. try again.", isError: true };
  }
}

/**
 * Protected profile route. Edits display name + preferred streaming service,
 * surfaces archived (completed) clubs, handles account deletion, sets a
 * password / links Google (MysteryMixClub-ali8.6, ADR 0007), and exposes the
 * log-out-of-all-devices action (MYS-36, MYS-61).
 */
export function ProfileRoute() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { userId, displayName, email, applyDisplayName, logout, logoutAll } = useAuth();

  const [preferredService, setPreferredService] = useState<
    "spotify" | "youtube" | "deezer" | null
  >(null);
  const [archived, setArchived] = useState<Club[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [savingService, setSavingService] = useState(false);
  const [saveServiceError, setSaveServiceError] = useState<string | null>(null);
  const [savedService, setSavedService] = useState(false);

  const [hasPassword, setHasPassword] = useState(false);
  const [settingPassword, setSettingPassword] = useState(false);
  const [passwordFormError, setPasswordFormError] = useState<string | null>(null);

  const [googleEnabled, setGoogleEnabled] = useState(false);
  const [googleLinked, setGoogleLinked] = useState(false);
  const [linkingGoogle, setLinkingGoogle] = useState(false);
  const [linkGoogleError, setLinkGoogleError] = useState<string | null>(null);
  // Read once, lazily, from whatever ?google_link= the redirect back from
  // Google's consent screen landed with -- stripped from the URL below so a
  // reload never re-shows a stale outcome.
  const [googleLinkNotice] = useState<{
    message: string;
    isError: boolean;
  } | null>(() => {
    const outcome = searchParams.get("google_link");
    return outcome ? googleLinkOutcomeCopy(outcome) : null;
  });

  const [logoutAllBusy, setLogoutAllBusy] = useState(false);

  const [exportingData, setExportingData] = useState(false);
  const [exportDataError, setExportDataError] = useState<string | null>(null);

  const [deletingAccount, setDeletingAccount] = useState(false);
  const [deleteAccountError, setDeleteAccountError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [clubs, profile] = await Promise.all([getClubs(), getMe()]);
        if (cancelled) return;
        const completed = clubs
          .filter((l) => l.state === "complete")
          .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""));
        setArchived(completed);
        setPreferredService(
          (profile.preferred_service as "spotify" | "youtube" | "deezer" | null) ?? null,
        );

        // A successful google-link redirect (?google_link=linked) means the
        // profile we just fetched may already be stale -- re-fetch once,
        // sequentially, so `googleLinked` flips without a manual refresh. Done
        // here (not in a second, parallel effect) so there's no race between
        // this load and that one over which response wins.
        let latestProfile = profile;
        if (searchParams.get("google_link") === "linked") {
          try {
            latestProfile = await getMe();
          } catch {
            // Keep the profile from the initial load -- the notice already
            // told the user linking succeeded, and the next full page load
            // will catch up.
          }
          if (cancelled) return;
        }
        setHasPassword(latestProfile.has_password);
        setGoogleLinked(latestProfile.google_linked);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "couldn't load your profile. try again.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Mount-only: `searchParams` is read for its one-time redirect flag, not
    // tracked as a value to re-run this load for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Whether Google sign-in is configured at all -- same fail-safe reasoning as
  // EmailEntryScreen: a failed/unconfigured check hides the Google subsection
  // rather than showing one that would just 404 on click.
  useEffect(() => {
    let cancelled = false;
    getGoogleEnabled()
      .then((r) => {
        if (!cancelled) setGoogleEnabled(r.enabled);
      })
      .catch(() => {
        if (!cancelled) setGoogleEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Strip ?google_link= as soon as it has been read (the message itself was
  // already captured into state above, on first render) so a reload or
  // bookmark never resurfaces a stale outcome.
  useEffect(() => {
    if (!searchParams.has("google_link")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("google_link");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 2000);
    return () => window.clearTimeout(timer);
  }, [saved]);

  useEffect(() => {
    if (!savedService) return;
    const timer = window.setTimeout(() => setSavedService(false), 2000);
    return () => window.clearTimeout(timer);
  }, [savedService]);

  async function handleSaveName(name: string) {
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const profile = await updateDisplayName(name);
      applyDisplayName(profile.display_name);
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "that didn't save. try again.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSavePreferredService(
    service: "spotify" | "youtube" | "deezer" | null,
  ) {
    setSavingService(true);
    setSaveServiceError(null);
    setSavedService(false);
    try {
      await updatePreferredService(service);
      setPreferredService(service);
      setSavedService(true);
    } catch (err) {
      setSaveServiceError(
        err instanceof ApiError ? err.message : "that didn't save. try again.",
      );
    } finally {
      setSavingService(false);
    }
  }

  async function handleSetPassword(password: string) {
    setPasswordFormError(null);
    // Same client-side bounds LoginRoute's register flow checks before
    // submitting: a length outside them 422s with FastAPI's list-shaped
    // validation body, which readErrorMessage() can't render as prose --
    // catching it here avoids ever sending that request.
    if (password.length < PASSWORD_MIN_LENGTH) {
      setPasswordFormError(`use at least ${PASSWORD_MIN_LENGTH} characters.`);
      return;
    }
    if (password.length > PASSWORD_MAX_LENGTH) {
      setPasswordFormError(`use ${PASSWORD_MAX_LENGTH} characters or fewer.`);
      return;
    }
    setSettingPassword(true);
    try {
      await apiSetPassword(password);
      setHasPassword(true);
    } catch (err) {
      setPasswordFormError(err instanceof ApiError ? err.message : "that didn't save. try again.");
    } finally {
      setSettingPassword(false);
    }
  }

  async function handleLinkGoogle() {
    setLinkingGoogle(true);
    setLinkGoogleError(null);
    try {
      const { authorize_url } = await startGoogleLink();
      // A real top-level navigation to Google's consent screen -- fetch can't
      // follow this, so the caller does it (mirrors connectSpotify's contract).
      window.location.href = authorize_url;
    } catch (err) {
      setLinkGoogleError(err instanceof ApiError ? err.message : "that didn't work. try again.");
      setLinkingGoogle(false);
    }
  }

  async function handleLogoutAll() {
    setLogoutAllBusy(true);
    try {
      await logoutAll();
    } finally {
      setLogoutAllBusy(false);
    }
  }

  async function handleExportData() {
    setExportingData(true);
    setExportDataError(null);
    try {
      const data = await exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `mysterymixclub-data-export-${new Date().toISOString().slice(0, 10)}.json`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportDataError(
        err instanceof ApiError ? err.message : "couldn't export your data. try again.",
      );
    } finally {
      setExportingData(false);
    }
  }

  async function handleDeleteAccount() {
    setDeletingAccount(true);
    setDeleteAccountError(null);
    try {
      await deleteAccount();
      // Clear local auth state; navigate unconditionally even if logout call fails
      // (sessions already invalidated server-side by the delete).
      try {
        await logout();
      } catch {
        // ignore
      }
      navigate("/");
    } catch (err) {
      setDeleteAccountError(
        err instanceof ApiError ? err.message : "couldn't delete account. try again.",
      );
      setDeletingAccount(false);
    }
  }

  return (
    <ProfileScreen
      userId={userId}
      displayName={displayName}
      email={email}
      preferredService={preferredService}
      archivedClubs={archived}
      loading={loading}
      error={error}
      onOpenClub={(id) => navigate(`/clubs/${id}`)}
      onSaveName={handleSaveName}
      saving={saving}
      saveError={saveError}
      saved={saved}
      onSavePreferredService={handleSavePreferredService}
      savingService={savingService}
      saveServiceError={saveServiceError}
      savedService={savedService}
      hasPassword={hasPassword}
      onSetPassword={handleSetPassword}
      settingPassword={settingPassword}
      setPasswordError={passwordFormError}
      googleEnabled={googleEnabled}
      googleLinked={googleLinked}
      onLinkGoogle={handleLinkGoogle}
      linkingGoogle={linkingGoogle}
      linkGoogleError={linkGoogleError}
      googleLinkNotice={googleLinkNotice}
      onLogoutAll={handleLogoutAll}
      logoutAllBusy={logoutAllBusy}
      onExportData={handleExportData}
      exportingData={exportingData}
      exportDataError={exportDataError}
      onDeleteAccount={handleDeleteAccount}
      deletingAccount={deletingAccount}
      deleteAccountError={deleteAccountError}
    />
  );
}
