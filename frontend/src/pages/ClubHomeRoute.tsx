import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ClubHomeScreen } from "./ClubHomeScreen";
import {
  ApiError,
  createInvite,
  deleteClub,
  getClub,
  getClubLeaderboard,
  getClubMembers,
  getResults,
  getMixes,
  removeMember,
  updateClub,
  updateMemberRole,
  updateMix,
  type Club,
  type LeaderboardEntry,
  type ClubMember,
  type Mix,
  type MixResults,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { usePolling } from "../hooks/usePolling";

/**
 * Protected club-home route. Loads the club and its members in parallel,
 * gates the fixed-organizer-only affordance on userId === organizer_id
 * (isOrganizer) and the broader operational powers — mix management, club
 * settings, member removal/role changes — on isOrganizer OR the caller's own
 * member row having is_admin (isAdmin, co-organizer parity, MYS-99). Wires the
 * invite, edit, member-removal, and role-change actions back to the API. A
 * 403/404 (or any load failure) becomes a calm error the screen renders
 * alongside a back affordance, so the route never crashes on a club the
 * user can't see.
 */
export function ClubHomeRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [club, setClub] = useState<Club | null>(null);
  const [members, setMembers] = useState<ClubMember[]>([]);
  const [mixes, setMixes] = useState<Mix[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [mixResults, setMixResults] = useState<Record<string, MixResults>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [savingMixId, setSavingMixId] = useState<string | null>(null);
  const [updateMixError, setUpdateMixError] = useState<string | null>(null);

  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  // Co-organizer promote/demote (MYS-99).
  const [changingRoleUserId, setChangingRoleUserId] = useState<string | null>(null);
  const [roleChangeError, setRoleChangeError] = useState<string | null>(null);

  // Organizer admin: delete club (MYS-124).
  const [deletingClub, setDeletingClub] = useState(false);
  const [deleteClubError, setDeleteClubError] = useState<string | null>(null);

  // Member self-leave (MYS-97).
  const [leavingClub, setLeavingClub] = useState(false);
  const [leaveClubError, setLeaveClubError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        const [loadedClub, loadedMembers, loadedMixes, loadedLeaderboard] = await Promise.all([
          getClub(id),
          getClubMembers(id),
          getMixes(id),
          getClubLeaderboard(id),
        ]);
        setClub(loadedClub);
        setMembers(loadedMembers);
        setMixes(loadedMixes);
        setLeaderboard(loadedLeaderboard);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "couldn't load this club.");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  // Silently refresh club + mix state every 60s so mix transitions
  // (e.g. organizer opens voting) surface without a manual page reload.
  usePolling(() => {
    if (!id) return;
    void (async () => {
      try {
        const [updatedClub, updatedMixes, updatedLeaderboard] = await Promise.all([
          getClub(id),
          getMixes(id),
          getClubLeaderboard(id),
        ]);
        setClub(updatedClub);
        setMixes(updatedMixes);
        setLeaderboard(updatedLeaderboard);
      } catch {
        // Non-fatal — stale data beats an error flash on a background refresh.
      }
    })();
  });

  // Closed mixes get a winner + most-noted summary on their card. Results live
  // behind a separate endpoint, so fetch them for every closed mix in parallel
  // once the slate is known. Failures are non-fatal — a card simply shows no
  // summary rather than breaking the list.
  useEffect(() => {
    const closed = mixes.filter((r) => r.state === "closed");
    if (closed.length === 0) return;
    let cancelled = false;
    void (async () => {
      const entries = await Promise.all(
        closed.map(async (mix) => {
          try {
            return [mix.id, await getResults(mix.id)] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      setMixResults((current) => {
        const next = { ...current };
        for (const entry of entries) {
          if (entry) next[entry[0]] = entry[1];
        }
        return next;
      });
    })();
    return () => {
      cancelled = true;
    };
  }, [mixes]);

  const isOrganizer = !!userId && club?.organizer_id === userId;
  // Co-organizers (role === "admin") get parity with the fixed organizer on
  // operational powers (mix management, club settings, member removal) —
  // MYS-99. isOrganizer stays narrower, for the one case that still cares
  // about the fixed organizer specifically (see the destructive-actions
  // section in ClubHomeScreen).
  const ownMember = members.find((m) => m.user_id === userId);
  const isAdmin = isOrganizer || ownMember?.is_admin === true;

  async function handleDeleteClub() {
    if (!id) return;
    setDeletingClub(true);
    setDeleteClubError(null);
    try {
      await deleteClub(id);
      navigate("/home");
    } catch (err) {
      // The backend's 409 detail ("cannot delete a club that is in progress")
      // is calm enough to show verbatim.
      setDeleteClubError(
        err instanceof ApiError ? err.message : "couldn't delete the club. try again.",
      );
      setDeletingClub(false);
    }
  }

  async function handleGenerateInvite() {
    if (!id) return;
    setGeneratingInvite(true);
    setInviteError(null);
    try {
      const invite = await createInvite(id);
      // Canonical invite path is /invite/:token (what the backend emails too);
      // /join/:token still resolves as a legacy alias.
      setInviteUrl(`${window.location.origin}/invite/${invite.token}`);
    } catch (err) {
      setInviteError(
        err instanceof ApiError ? err.message : "couldn't generate an invite. try again.",
      );
    } finally {
      setGeneratingInvite(false);
    }
  }

  // Edit a single mix's theme/description in place. Returns true on success so
  // the inline editor can close itself. On success we patch the mix into local
  // state rather than refetch — the rest of the slate is unchanged.
  async function handleUpdateMix(
    mixId: string,
    input: { theme?: string | null; description?: string | null },
  ): Promise<boolean> {
    if (!id) return false;
    setSavingMixId(mixId);
    setUpdateMixError(null);
    try {
      const updated = await updateMix(mixId, input);
      setMixes((current) => current.map((r) => (r.id === mixId ? updated : r)));
      return true;
    } catch (err) {
      setUpdateMixError(
        err instanceof ApiError ? err.message : "couldn't save the mystery mix. try again.",
      );
      return false;
    } finally {
      setSavingMixId(null);
    }
  }

  async function handleUpdateClub(input: {
    name?: string;
    description?: string | null;
    total_mixes?: number;
    submission_window_hours?: number;
    voting_window_hours?: number;
  }) {
    if (!id) return;
    setUpdating(true);
    setUpdateError(null);
    try {
      const updated = await updateClub(id, input);
      setClub(updated);
      // Changing total_mixes reconciles the mix slate server-side (adds or
      // removes trailing pending mixes); refetch so the list matches. Non-fatal.
      if (input.total_mixes !== undefined) {
        try {
          setMixes(await getMixes(id));
        } catch {
          // The club header is already current; leave the list as-is.
        }
      }
    } catch (err) {
      setUpdateError(err instanceof ApiError ? err.message : "couldn't save changes. try again.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleLeaveClub() {
    if (!id || !userId) return;
    setLeavingClub(true);
    setLeaveClubError(null);
    try {
      await removeMember(id, userId);
      navigate("/home");
    } catch (err) {
      setLeaveClubError(
        err instanceof ApiError ? err.message : "couldn't leave the club. try again.",
      );
      setLeavingClub(false);
    }
  }

  async function handleRemoveMember(memberUserId: string) {
    if (!id) return;
    setRemovingUserId(memberUserId);
    setRemoveError(null);
    try {
      await removeMember(id, memberUserId);
      setMembers((current) => current.filter((m) => m.user_id !== memberUserId));
    } catch (err) {
      setRemoveError(
        err instanceof ApiError ? err.message : "couldn't remove that member. try again.",
      );
    } finally {
      setRemovingUserId(null);
    }
  }

  async function handleChangeMemberRole(memberUserId: string, role: "admin" | "member") {
    if (!id) return;
    setChangingRoleUserId(memberUserId);
    setRoleChangeError(null);
    try {
      const updated = await updateMemberRole(id, memberUserId, role);
      setMembers((current) => current.map((m) => (m.user_id === memberUserId ? updated : m)));
    } catch (err) {
      setRoleChangeError(
        err instanceof ApiError ? err.message : "couldn't update that member's role. try again.",
      );
    } finally {
      setChangingRoleUserId(null);
    }
  }

  // While loading (or if the club never resolved without an error), keep the
  // screen in its loading state. The screen reads `club` only after the
  // loading/error guards, so the empty placeholder is never rendered.
  const placeholderClub: Club = {
    id: id ?? "",
    name: "",
    description: null,
    organizer_id: "",
    total_mixes: 0,
    votes_per_player: 0,
    songs_per_submission: 1,
    current_mix: 0,
    state: "active",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    created_at: "",
    completed_at: null,
  };

  return (
    <ClubHomeScreen
      club={club ?? placeholderClub}
      members={members}
      mixes={mixes}
      leaderboard={leaderboard}
      userId={userId}
      mixResults={mixResults}
      isOrganizer={isOrganizer}
      isAdmin={isAdmin}
      loading={loading || (!club && !error)}
      error={error}
      onBack={() => navigate("/home")}
      onOpenMix={(mixId) => navigate(`/mixes/${mixId}`)}
      onUpdateMix={handleUpdateMix}
      savingMixId={savingMixId}
      updateMixError={updateMixError}
      inviteUrl={inviteUrl}
      onGenerateInvite={handleGenerateInvite}
      generatingInvite={generatingInvite}
      inviteError={inviteError}
      onUpdateClub={handleUpdateClub}
      updating={updating}
      updateError={updateError}
      onRemoveMember={handleRemoveMember}
      removingUserId={removingUserId}
      removeError={removeError}
      onChangeMemberRole={handleChangeMemberRole}
      changingRoleUserId={changingRoleUserId}
      roleChangeError={roleChangeError}
      onDeleteClub={handleDeleteClub}
      deletingClub={deletingClub}
      deleteClubError={deleteClubError}
      onLeaveClub={handleLeaveClub}
      leavingClub={leavingClub}
      leaveClubError={leaveClubError}
    />
  );
}
