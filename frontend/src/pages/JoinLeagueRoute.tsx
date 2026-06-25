import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
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
 * this route is not behind ProtectedRoute.
 *
 * Two paths (v2):
 *  - Logged-OUT: preview → "sign in" stashes the invite path and routes to
 *    /login, which carries the token through request+verify; the backend
 *    auto-joins on verify, so there is no explicit accept step for this path.
 *    After verify the user lands here authenticated and is dropped straight into
 *    the league (the auto-join already happened; accept is idempotent).
 *  - Logged-IN: preview → accept (POST /invites/:token/accept) → join.
 */
export function JoinLeagueRoute() {
  const { token } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated } = useAuth();

  // A missing :token can't resolve to anything, so it's the not-found state
  // from the first render — no effect-time setState needed for that case.
  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [notFound, setNotFound] = useState(!token);
  // An expired link (410) reads differently from a bad one — calm "ask for a
  // new one" copy rather than "didn't work".
  const [expired, setExpired] = useState(false);
  const [joining, setJoining] = useState(false);
  const [joinError, setJoinError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    void (async () => {
      try {
        const result = await getInvitePreview(token);
        setPreview(result);
      } catch (err) {
        // A 410 means the link expired; anything else is treated as not-found.
        // Either way there's nothing to preview, so we show a calm state, not a crash.
        if (err instanceof ApiError && err.status === 410) {
          setExpired(true);
        } else {
          setNotFound(true);
        }
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
      // A link that expired between preview and accept flips to the expired state.
      if (err instanceof ApiError && err.status === 410) {
        setExpired(true);
        setJoining(false);
        return;
      }
      setJoinError(
        err instanceof ApiError ? err.message : "couldn't join the league. try again.",
      );
      setJoining(false);
    }
  }

  function handleSignIn() {
    // Stash the exact path the visitor landed on (/invite/:token from email,
    // or the /join/:token alias) so /home returns them here after sign-in.
    localStorage.setItem("pendingInvitePath", location.pathname);
    navigate("/login");
  }

  return (
    <JoinLeagueScreen
      preview={preview}
      loading={loading}
      notFound={notFound}
      expired={expired}
      isAuthenticated={isAuthenticated}
      onJoin={handleJoin}
      joining={joining}
      joinError={joinError}
      onSignIn={handleSignIn}
    />
  );
}
