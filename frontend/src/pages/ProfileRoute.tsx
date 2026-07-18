import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ProfileScreen } from "./ProfileScreen";
import {
  ApiError,
  deleteAccount,
  exportMyData,
  getLeagues,
  getMe,
  updateDisplayName,
  updatePreferredService,
  type League,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected profile route. Edits display name + preferred streaming service,
 * surfaces archived (completed) leagues, handles account deletion, and exposes
 * the log-out-of-all-devices action (MYS-36, MYS-61).
 */
export function ProfileRoute() {
  const navigate = useNavigate();
  const { userId, displayName, email, applyDisplayName, logout, logoutAll } = useAuth();

  const [preferredService, setPreferredService] = useState<
    "spotify" | "youtube" | "deezer" | null
  >(null);
  const [archived, setArchived] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const [savingService, setSavingService] = useState(false);
  const [saveServiceError, setSaveServiceError] = useState<string | null>(null);
  const [savedService, setSavedService] = useState(false);

  const [logoutAllBusy, setLogoutAllBusy] = useState(false);

  const [exportingData, setExportingData] = useState(false);
  const [exportDataError, setExportDataError] = useState<string | null>(null);

  const [deletingAccount, setDeletingAccount] = useState(false);
  const [deleteAccountError, setDeleteAccountError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [leagues, profile] = await Promise.all([getLeagues(), getMe()]);
        if (cancelled) return;
        const completed = leagues
          .filter((l) => l.state === "complete")
          .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""));
        setArchived(completed);
        setPreferredService(
          (profile.preferred_service as "spotify" | "youtube" | "deezer" | null) ?? null,
        );
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
      archivedLeagues={archived}
      loading={loading}
      error={error}
      onOpenLeague={(id) => navigate(`/clubs/${id}`)}
      onSaveName={handleSaveName}
      saving={saving}
      saveError={saveError}
      saved={saved}
      onSavePreferredService={handleSavePreferredService}
      savingService={savingService}
      saveServiceError={saveServiceError}
      savedService={savedService}
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
