import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { LeagueHomeScreen } from "./LeagueHomeScreen";
import {
  ApiError,
  createInvite,
  createRound,
  getLeague,
  getLeagueMembers,
  getRounds,
  removeMember,
  updateLeague,
  type League,
  type LeagueMember,
  type Round,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [creatingRound, setCreatingRound] = useState(false);
  const [createRoundError, setCreateRoundError] = useState<string | null>(null);

  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const [generatingInvite, setGeneratingInvite] = useState(false);
  const [inviteError, setInviteError] = useState<string | null>(null);

  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const [removingUserId, setRemovingUserId] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        const [loadedLeague, loadedMembers, loadedRounds] = await Promise.all([
          getLeague(id),
          getLeagueMembers(id),
          getRounds(id),
        ]);
        setLeague(loadedLeague);
        setMembers(loadedMembers);
        setRounds(loadedRounds);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "couldn't load this league.");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  const isOrganizer = !!userId && league?.organizer_id === userId;

  async function handleGenerateInvite() {
    if (!id) return;
    setGeneratingInvite(true);
    setInviteError(null);
    try {
      const invite = await createInvite(id);
      setInviteUrl(`${window.location.origin}/join/${invite.token}`);
    } catch (err) {
      setInviteError(
        err instanceof ApiError ? err.message : "couldn't generate an invite. try again.",
      );
    } finally {
      setGeneratingInvite(false);
    }
  }

  async function handleCreateRound(theme: string, votesPerPlayer?: number) {
    if (!id) return;
    setCreatingRound(true);
    setCreateRoundError(null);
    try {
      const round = await createRound(id, {
        theme,
        ...(votesPerPlayer ? { votes_per_player: votesPerPlayer } : {}),
      });
      setRounds((current) => [...current, round]);
    } catch (err) {
      setCreateRoundError(
        err instanceof ApiError ? err.message : "couldn't create the round. try again.",
      );
    } finally {
      setCreatingRound(false);
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
    } catch (err) {
      setUpdateError(err instanceof ApiError ? err.message : "couldn't save changes. try again.");
    } finally {
      setUpdating(false);
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
    current_round: 0,
    state: "active",
    created_at: "",
    completed_at: null,
  };

  return (
    <LeagueHomeScreen
      league={league ?? placeholderLeague}
      members={members}
      rounds={rounds}
      isOrganizer={isOrganizer}
      loading={loading || (!league && !error)}
      error={error}
      onBack={() => navigate("/home")}
      onOpenRound={(roundId) => navigate(`/rounds/${roundId}`)}
      onCreateRound={handleCreateRound}
      creatingRound={creatingRound}
      createRoundError={createRoundError}
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
    />
  );
}
