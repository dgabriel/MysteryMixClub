import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MyClubsScreen } from "./MyClubsScreen";
import { ApiError, getClubs, type Club } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Protected home route — the My Clubs landing. On mount it first honours a
 * pending invite path stored before sign-in (the join flow stashes it when an
 * unauthenticated user follows an invite link), redirecting there instead of
 * loading clubs. Otherwise it fetches the current user's clubs and wires
 * MyClubsScreen's actions to navigation. Profile / admin / logout now live in
 * the shared TopNav, so this route no longer owns them.
 */
export function HomeRoute() {
  const navigate = useNavigate();
  const { displayName, preferredService } = useAuth();
  const [clubs, setClubs] = useState<Club[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const pending = localStorage.getItem("pendingInvitePath");
    if (pending) {
      localStorage.removeItem("pendingInvitePath");
      navigate(pending, { replace: true });
      return;
    }

    void (async () => {
      try {
        const result = await getClubs();
        setClubs(result);
      } catch (err) {
        setError(
          err instanceof ApiError ? err.message : "couldn't load your clubs. try again.",
        );
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  return (
    <MyClubsScreen
      displayName={displayName}
      clubs={clubs}
      loading={loading}
      error={error}
      preferredService={preferredService}
      onCreateClub={() => navigate("/clubs/new")}
      onOpenClub={(id) => navigate(`/clubs/${id}`)}
    />
  );
}
