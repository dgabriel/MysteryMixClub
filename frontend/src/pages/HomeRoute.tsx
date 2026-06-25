import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MyLeaguesScreen } from "./MyLeaguesScreen";
import { ApiError, getLeagues, type League } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected home route — the My Leagues landing. On mount it first honours a
 * pending invite path stored before sign-in (the join flow stashes it when an
 * unauthenticated user follows an invite link), redirecting there instead of
 * loading leagues. Otherwise it fetches the current user's leagues and wires
 * MyLeaguesScreen's actions to navigation and the auth context.
 */
export function HomeRoute() {
  const navigate = useNavigate();
  const { displayName, logout, isPlatformAdmin } = useAuth();
  const [leagues, setLeagues] = useState<League[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    const pending = localStorage.getItem("pendingInvitePath");
    if (pending) {
      localStorage.removeItem("pendingInvitePath");
      navigate(pending, { replace: true });
      return;
    }

    void (async () => {
      try {
        const result = await getLeagues();
        setLeagues(result);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "couldn't load your leagues. try again.",
        );
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  async function handleLogout() {
    setLoggingOut(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setLoggingOut(false);
    }
  }

  return (
    <MyLeaguesScreen
      displayName={displayName}
      leagues={leagues}
      loading={loading}
      error={error}
      onCreateLeague={() => navigate("/leagues/new")}
      onOpenLeague={(id) => navigate(`/leagues/${id}`)}
      onLogout={handleLogout}
      loggingOut={loggingOut}
      isPlatformAdmin={isPlatformAdmin}
      onOpenAdmin={() => navigate("/admin")}
    />
  );
}
