import { useState } from "react";
import { Navigate } from "react-router-dom";
import { AdminScreen } from "./AdminScreen";
import {
  ApiError,
  adminCreateInvite,
  adminDeleteUser,
  adminSearchUsers,
  type AdminUser,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected platform-admin route. Already behind ProtectedRoute for auth +
 * onboarding; here we additionally gate on `isPlatformAdmin` and bounce a
 * non-admin to /home (the nav entry is also hidden for non-admins, so this is a
 * defence-in-depth guard for a hand-typed URL). Wires the user search, the
 * hard-delete action, and platform invite generation (MYS-182) to the admin API.
 */
export function AdminRoute() {
  const { isPlatformAdmin } = useAuth();

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AdminUser[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const [platformInviteUrl, setPlatformInviteUrl] = useState<string | null>(null);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  if (!isPlatformAdmin) {
    return <Navigate to="/home" replace />;
  }

  async function handleSearch() {
    const q = query.trim();
    if (!q) return;
    setSearching(true);
    setSearchError(null);
    try {
      const found = await adminSearchUsers(q);
      setResults(found);
      setSearched(true);
    } catch (err) {
      setSearchError(
        err instanceof ApiError ? err.message : "couldn't run that search. try again.",
      );
    } finally {
      setSearching(false);
    }
  }

  async function handleDeleteUser(userId: string) {
    setDeletingUserId(userId);
    setDeleteError(null);
    try {
      await adminDeleteUser(userId);
      setResults((current) => current.filter((u) => u.id !== userId));
    } catch (err) {
      // The backend's 409 self-delete detail is calm enough to show verbatim.
      setDeleteError(
        err instanceof ApiError ? err.message : "couldn't delete that account. try again.",
      );
    } finally {
      setDeletingUserId(null);
    }
  }

  async function handleGenerateInvite() {
    setGeneratingInvite(true);
    setInviteError(null);
    try {
      const invite = await adminCreateInvite();
      // Canonical invite path is /invite/:token (matches the per-club flow).
      setPlatformInviteUrl(`${window.location.origin}/invite/${invite.token}`);
    } catch (err) {
      setInviteError(
        err instanceof ApiError ? err.message : "couldn't generate an invite. try again.",
      );
    } finally {
      setGeneratingInvite(false);
    }
  }

  return (
    <AdminScreen
      query={query}
      onQueryChange={setQuery}
      onSearch={handleSearch}
      searching={searching}
      results={results}
      searched={searched}
      searchError={searchError}
      onDeleteUser={handleDeleteUser}
      deletingUserId={deletingUserId}
      deleteError={deleteError}
      platformInviteUrl={platformInviteUrl}
      generatingInvite={generatingInvite}
      inviteError={inviteError}
      onGenerateInvite={handleGenerateInvite}
    />
  );
}
