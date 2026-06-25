import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ProfileScreen } from "./ProfileScreen";
import { ApiError, getLeagues, updateDisplayName, type League } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected profile route. Edits the display name (PATCH /users/me, mirrored into
 * the auth context so the rest of the app updates without a refetch) and lists
 * the user's archived (completed) leagues, most-recently-completed first, each
 * linkable to its league home. A load failure becomes a calm error.
 */
export function ProfileRoute() {
  const navigate = useNavigate();
  const { displayName, email, applyDisplayName } = useAuth();

  const [archived, setArchived] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const leagues = await getLeagues();
        if (cancelled) return;
        // Archived = completed leagues, newest-completed first. completed_at can
        // in principle be null on an oddly-shaped row; sort those last.
        const completed = leagues
          .filter((l) => l.state === "complete")
          .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""));
        setArchived(completed);
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

  // Clear the brief "saved" acknowledgement after a moment.
  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 2000);
    return () => window.clearTimeout(timer);
  }, [saved]);

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

  return (
    <ProfileScreen
      displayName={displayName}
      email={email}
      archivedLeagues={archived}
      loading={loading}
      error={error}
      onOpenLeague={(id) => navigate(`/leagues/${id}`)}
      onSaveName={handleSaveName}
      saving={saving}
      saveError={saveError}
      saved={saved}
    />
  );
}
