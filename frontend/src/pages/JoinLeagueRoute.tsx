import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { JoinLeagueScreen } from "./JoinLeagueScreen";
import {
  ApiError,
  acceptInvite,
  getInvitePreview,
  type InvitePreview,
} from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Public join route. The invite preview is visible to anyone with the link, so
 * this route is not behind ProtectedRoute. An authenticated visitor can join
 * directly; an unauthenticated one stashes the invite path and is sent to sign
 * in, after which /home picks the path back up and returns them here.
 */
export function JoinLeagueRoute() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  // A missing :token can't resolve to anything, so it's the not-found state
  // from the first render — no effect-time setState needed for that case.
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [notFound, setNotFound] = useState(!token);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    void (async () => {
      try {
        const result = await getInvitePreview(token);
        setPreview(result);
      } catch {
        // Any failure to resolve the invite is treated the same way: there's
        // nothing to preview, so show the not-found state rather than a crash.
        setNotFound(true);
      } finally {
        setLoading(false);
      }
    })();
  }, [token]);

  async function handleJoin() {
    if (!token) return;
    setJoining(true);
    setJoinError(null);
    try {
      const league = await acceptInvite(token);
      navigate(`/leagues/${league.id}`, { replace: true });
    } catch (err) {
      setJoinError(
        err instanceof ApiError ? err.message : "couldn't join the league. try again.",
      );
      setJoining(false);
    }
  }

  function handleSignIn() {
    localStorage.setItem("pendingInvitePath", `/join/${token}`);
    navigate("/login");
  }

  return (
    <JoinLeagueScreen
      preview={preview}
      loading={loading}
      notFound={notFound}
      isAuthenticated={isAuthenticated}
      onJoin={handleJoin}
      joining={joining}
      joinError={joinError}
      onSignIn={handleSignIn}
    />
  );
}
