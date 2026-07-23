import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { AdminScreen } from "./AdminScreen";
import {
  ApiError,
  adminCreateInvite,
  adminDeleteUser,
  adminInviteFromWaitlist,
  adminListWaitlist,
  adminSearchUsers,
  connectSpotify,
  getSpotifyStatus,
  type AdminUser,
  type SpotifyStatus,
  type WaitlistEntry,
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

  // Waitlist (MYS-215, temporary).
  const [waitlistEntries, setWaitlistEntries] = useState<WaitlistEntry[]>([]);
  const [waitlistLoading, setWaitlistLoading] = useState(true);
  const [waitlistError, setWaitlistError] = useState<string | null>(null);
  const [invitingEntryId, setInvitingEntryId] = useState<string | null>(null);

  // Spotify shared-account connect (MYS-169): ops-only, (re)links the one
  // dedicated MysteryMixClub Spotify account playlist generation runs under.
  const [searchParams, setSearchParams] = useSearchParams();
  const [spotifyStatus, setSpotifyStatus] = useState<SpotifyStatus | null>(null);
  const [spotifyStatusLoading, setSpotifyStatusLoading] = useState(true);
  const [connectingSpotify, setConnectingSpotify] = useState(false);
  const [spotifyError, setSpotifyError] = useState<string | null>(null);
  // Set once, from the ?spotify= flag the OAuth callback lands back with;
  // cleared from the URL immediately so a refresh doesn't repeat it.
  const [spotifyResult] = useState(() => searchParams.get("spotify"));

  useEffect(() => {
    if (!spotifyResult) return;
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("spotify");
        return next;
      },
      { replace: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let active = true;
    getSpotifyStatus()
      .then((status) => {
        if (active) setSpotifyStatus(status);
      })
      .catch((err: unknown) => {
        if (active) {
          setSpotifyError(
            err instanceof ApiError ? err.message : "couldn't load spotify status.",
          );
        }
      })
      .finally(() => {
        if (active) setSpotifyStatusLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isPlatformAdmin]);

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let active = true;
    adminListWaitlist()
      .then((entries) => {
        if (active) setWaitlistEntries(entries);
      })
      .catch((err: unknown) => {
        if (active) {
          setWaitlistError(
            err instanceof ApiError ? err.message : "couldn't load the waitlist.",
          );
        }
      })
      .finally(() => {
        if (active) setWaitlistLoading(false);
      });
    return () => {
      active = false;
    };
  }, [isPlatformAdmin]);

  if (!isPlatformAdmin) {
    return <Navigate to="/home" replace />;
  }

  async function handleInviteFromWaitlist(entryId: string) {
    setInvitingEntryId(entryId);
    setWaitlistError(null);
    try {
      const updated = await adminInviteFromWaitlist(entryId);
      setWaitlistEntries((current) => current.map((e) => (e.id === entryId ? updated : e)));
    } catch (err) {
      setWaitlistError(
        err instanceof ApiError ? err.message : "couldn't send that invite. try again.",
      );
    } finally {
      setInvitingEntryId(null);
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

  async function handleConnectSpotify() {
    setConnectingSpotify(true);
    setSpotifyError(null);
    try {
      const { authorize_url } = await connectSpotify("/admin");
      window.location.href = authorize_url;
    } catch (err) {
      setSpotifyError(
        err instanceof ApiError ? err.message : "couldn't start the spotify connection. try again.",
      );
      setConnectingSpotify(false);
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
      waitlistEntries={waitlistEntries}
      waitlistLoading={waitlistLoading}
      waitlistError={waitlistError}
      invitingEntryId={invitingEntryId}
      onInviteFromWaitlist={handleInviteFromWaitlist}
      spotifyStatus={spotifyStatus}
      spotifyStatusLoading={spotifyStatusLoading}
      connectingSpotify={connectingSpotify}
      spotifyError={spotifyError}
      spotifyResult={spotifyResult}
      onConnectSpotify={handleConnectSpotify}
    />
  );
}
