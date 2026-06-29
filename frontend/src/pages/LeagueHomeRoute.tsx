import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { LeagueHomeScreen } from "./LeagueHomeScreen";
import {
  ApiError,
  createInvite,
  deleteLeague,
  getLeague,
  getLeagueLeaderboard,
  getLeagueMembers,
  getResults,
  getRounds,
  removeMember,
  updateLeague,
  updateRound,
  type League,
  type LeaderboardEntry,
  type LeagueMember,
  type Round,
  type RoundResults,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { usePolling } from "../hooks/usePolling";

/**
 * Protected league-home route. Loads the league and its members in parallel,
 * gates organizer controls on userId === organizer_id, and wires the invite,
 * edit, and member-removal actions back to the API. A 403/404 (or any load
 * failure) becomes a calm error the screen renders alongside a back affordance,
 * so the route never crashes on a league the user can't see.
 */
export function LeagueHomeRoute() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [league, setLeague] = useState<League | null>(null);
  const [members, setMembers] = useState<LeagueMember[]>([]);
  const [rounds, setRounds] = useState<Round[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [roundResults, setRoundResults] = useState<Record<string, RoundResults>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [savingRoundId, setSavingRoundId] = useState<string | null>(null);
  const [updateRoundError, setUpdateRoundError] = useState<string | null>(null);

  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  // Organizer admin: delete league (MYS-124).
  const [deletingLeague, setDeletingLeague] = useState(false);
  const [deleteLeagueError, setDeleteLeagueError] = useState<string | null>(null);

  // Member self-leave (MYS-97).
  const [leavingLeague, setLeavingLeague] = useState(false);
  const [leaveLeagueError, setLeaveLeagueError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        const [loadedLeague, loadedMembers, loadedRounds, loadedLeaderboard] = await Promise.all([
          getLeague(id),
          getLeagueMembers(id),
          getRounds(id),
          getLeagueLeaderboard(id),
        ]);
        setLeague(loadedLeague);
        setMembers(loadedMembers);
        setRounds(loadedRounds);
        setLeaderboard(loadedLeaderboard);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "couldn't load this league.");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  // Silently refresh league + round state every 60s so round transitions
  // (e.g. organizer opens voting) surface without a manual page reload.
  usePolling(() => {
    if (!id) return;
    void (async () => {
      try {
        const [updatedLeague, updatedRounds, updatedLeaderboard] = await Promise.all([
          getLeague(id),
          getRounds(id),
          getLeagueLeaderboard(id),
        ]);
        setLeague(updatedLeague);
        setRounds(updatedRounds);
        setLeaderboard(updatedLeaderboard);
      } catch {
        // Non-fatal — stale data beats an error flash on a background refresh.
      }
    })();
  });

  // Closed rounds get a winner + most-noted summary on their card. Results live
  // behind a separate endpoint, so fetch them for every closed round in parallel
  // once the slate is known. Failures are non-fatal — a card simply shows no
  // summary rather than breaking the list.
  useEffect(() => {
    const closed = rounds.filter((r) => r.state === "closed");
    if (closed.length === 0) return;
    let cancelled = false;
    void (async () => {
      const entries = await Promise.all(
        closed.map(async (round) => {
          try {
            return [round.id, await getResults(round.id)] as const;
          } catch {
            return null;
          }
        }),
      );
      if (cancelled) return;
      setRoundResults((current) => {
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
  }, [rounds]);

  const isOrganizer = !!userId && league?.organizer_id === userId;

  async function handleDeleteLeague() {
    if (!id) return;
    setDeletingLeague(true);
    setDeleteLeagueError(null);
    try {
      await deleteLeague(id);
      navigate("/home");
    } catch (err) {
      // The backend's 409 detail ("cannot delete a league that is in progress")
      // is calm enough to show verbatim.
      setDeleteLeagueError(
        err instanceof ApiError ? err.message : "couldn't delete the league. try again.",
      );
      setDeletingLeague(false);
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

  // Edit a single round's theme/description in place. Returns true on success so
  // the inline editor can close itself. On success we patch the round into local
  // state rather than refetch — the rest of the slate is unchanged.
  async function handleUpdateRound(
    roundId: string,
    input: { theme?: string | null; description?: string | null },
  ): Promise<boolean> {
    if (!id) return false;
    setSavingRoundId(roundId);
    setUpdateRoundError(null);
    try {
      const updated = await updateRound(roundId, input);
      setRounds((current) => current.map((r) => (r.id === roundId ? updated : r)));
      return true;
    } catch (err) {
      setUpdateRoundError(
        err instanceof ApiError ? err.message : "couldn't save the round. try again.",
      );
      return false;
    } finally {
      setSavingRoundId(null);
    }
  }

  async function handleUpdateLeague(input: {
    name?: string;
    description?: string | null;
    total_rounds?: number;
  }) {
    if (!id) return;
    setUpdating(true);
    setUpdateError(null);
    try {
      const updated = await updateLeague(id, input);
      setLeague(updated);
      // Changing total_rounds reconciles the round slate server-side (adds or
      // removes trailing pending rounds); refetch so the list matches. Non-fatal.
      if (input.total_rounds !== undefined) {
        try {
          setRounds(await getRounds(id));
        } catch {
          // The league header is already current; leave the list as-is.
        }
      }
    } catch (err) {
      setUpdateError(err instanceof ApiError ? err.message : "couldn't save changes. try again.");
    } finally {
      setUpdating(false);
    }
  }

  async function handleLeaveLeague() {
    if (!id || !userId) return;
    setLeavingLeague(true);
    setLeaveLeagueError(null);
    try {
      await removeMember(id, userId);
      navigate("/home");
    } catch (err) {
      setLeaveLeagueError(
        err instanceof ApiError ? err.message : "couldn't leave the league. try again.",
      );
      setLeavingLeague(false);
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

  // While loading (or if the league never resolved without an error), keep the
  // screen in its loading state. The screen reads `league` only after the
  // loading/error guards, so the empty placeholder is never rendered.
  const placeholderLeague: League = {
    id: id ?? "",
    name: "",
    description: null,
    organizer_id: "",
    total_rounds: 0,
    votes_per_player: 0,
    songs_per_submission: 1,
    current_round: 0,
    state: "active",
    default_vibe_mode: false,
    created_at: "",
    completed_at: null,
  };

  return (
    <LeagueHomeScreen
      league={league ?? placeholderLeague}
      members={members}
      rounds={rounds}
      leaderboard={leaderboard}
      userId={userId}
      roundResults={roundResults}
      isOrganizer={isOrganizer}
      loading={loading || (!league && !error)}
      error={error}
      onBack={() => navigate("/home")}
      onOpenRound={(roundId) => navigate(`/rounds/${roundId}`)}
      onUpdateRound={handleUpdateRound}
      savingRoundId={savingRoundId}
      updateRoundError={updateRoundError}
      inviteUrl={inviteUrl}
      onGenerateInvite={handleGenerateInvite}
      generatingInvite={generatingInvite}
      inviteError={inviteError}
      onUpdateLeague={handleUpdateLeague}
      updating={updating}
      updateError={updateError}
      onRemoveMember={handleRemoveMember}
      removingUserId={removingUserId}
      removeError={removeError}
      onDeleteLeague={handleDeleteLeague}
      deletingLeague={deletingLeague}
      deleteLeagueError={deleteLeagueError}
      onLeaveLeague={handleLeaveLeague}
      leavingLeague={leavingLeague}
      leaveLeagueError={leaveLeagueError}
    />
  );
}
