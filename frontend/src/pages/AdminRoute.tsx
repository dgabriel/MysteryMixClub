import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { AdminScreen } from "./AdminScreen";
import {
  ApiError,
  adminDeleteUser,
  adminListSpotifyPendingRounds,
  adminSearchUsers,
  createSpotifyPlaylist,
  type AdminSpotifyRound,
  type AdminUser,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected platform-admin route. Already behind ProtectedRoute for auth +
 * onboarding; here we additionally gate on `isPlatformAdmin` and bounce a
 * non-admin to /home (the nav entry is also hidden for non-admins, so this is a
 * defence-in-depth guard for a hand-typed URL). Wires the user search + the
 * hard-delete action, and the Spotify generate/regenerate list (MYS-169), to
 * the admin API.
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

  const [spotifyRounds, setSpotifyRounds] = useState<AdminSpotifyRound[]>([]);
  const [spotifyLoading, setSpotifyLoading] = useState(true);
  const [spotifyError, setSpotifyError] = useState<string | null>(null);
  const [generatingRoundId, setGeneratingRoundId] = useState<string | null>(null);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let active = true;
    adminListSpotifyPendingRounds()
      .then((rounds) => {
        if (active) setSpotifyRounds(rounds);
      })
      .catch((err) => {
        if (!active) return;
        setSpotifyError(
          err instanceof ApiError ? err.message : "couldn't load the round list. try again.",
        );
      })
      .finally(() => {
        if (active) setSpotifyLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isPlatformAdmin]);

  if (!isPlatformAdmin) {
    return <Navigate to="/home" replace />;
  }

  async function handleGenerateSpotifyPlaylist(roundId: string) {
    setGeneratingRoundId(roundId);
    setSpotifyError(null);
    try {
      const result = await createSpotifyPlaylist(roundId);
      setSpotifyRounds((current) =>
        current.map((r) => (r.round_id === roundId ? { ...r, playlist_url: result.playlist_url } : r)),
      );
    } catch (err) {
      setSpotifyError(
        err instanceof ApiError ? err.message : "couldn't generate that playlist. try again.",
      );
    } finally {
      setGeneratingRoundId(null);
    }
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
      spotifyRounds={spotifyRounds}
      spotifyLoading={spotifyLoading}
      spotifyError={spotifyError}
      onGenerateSpotifyPlaylist={handleGenerateSpotifyPlaylist}
      generatingRoundId={generatingRoundId}
    />
  );
}
