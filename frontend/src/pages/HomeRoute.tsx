import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { MyClubsScreen } from "./MyClubsScreen";
import { ApiError, getClubs, type Club } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { dismissGuide, isGuideDismissed } from "../data/onboardingGuides";

/**
 * Protected home route — the My Clubs landing. On mount it first honours a
 * pending invite path stored before sign-in (the join flow stashes it when an
 * unauthenticated user follows an invite link), redirecting there instead of
 * loading clubs. Otherwise it fetches the current user's clubs and wires
 * MyClubsScreen's actions to navigation. Profile / admin / logout now live in
 * the shared TopNav, so this route no longer owns them.
 *
 * Owns the empty-clubs welcome guide (MysteryMixClub-6eo8): shown once a
 * successfully loaded club list comes back empty, for an account that hasn't
 * dismissed it before -- never while still loading or on an error, and never
 * for the pending-invite redirect above, which leaves before a club list is
 * ever fetched here.
 */
export function HomeRoute() {
  const navigate = useNavigate();
  const { displayName, preferredService, userId } = useAuth();
  const [clubs, setClubs] = useState<Club[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showWelcomeGuide, setShowWelcomeGuide] = useState(false);

  useEffect(() => {
    const pending = localStorage.getItem("pendingInvitePath");
    if (pending) {
      localStorage.removeItem("pendingInvitePath");
      // `fromPendingInvite` lets JoinClubRoute tell "just auto-joined via this
      // sign-in" apart from "an existing member revisiting an old invite
      // link" -- both resolve to the same already_member:true preview, but
      // only the former should auto-show the invite-welcome guide.
      navigate(pending, { replace: true, state: { fromPendingInvite: true } });
      return;
    }

    void (async () => {
      try {
        const result = await getClubs();
        setClubs(result);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "couldn't load your clubs. try again.");
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  // Reactive rather than folded into the fetch above: `userId` can still be
  // null on that first pass (the profile fetch that fills it in runs
  // alongside, not before, this one) -- this re-evaluates once it lands
  // without needing a second network round trip.
  useEffect(() => {
    if (loading || error || clubs.length !== 0 || !userId) return;
    if (!isGuideDismissed("emptyClubs", userId)) {
      // Syncing from external state (localStorage), same pattern the rule
      // already accepts elsewhere (see MixDetailRoute's load() effect).
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setShowWelcomeGuide(true);
    }
  }, [loading, error, clubs, userId]);

  function dismissWelcomeGuide() {
    if (userId) dismissGuide("emptyClubs", userId);
    setShowWelcomeGuide(false);
  }

  function handleCreateClubFromGuide() {
    dismissWelcomeGuide();
    navigate("/clubs/new");
  }

  return (
    <MyClubsScreen
      displayName={displayName}
      clubs={clubs}
      loading={loading}
      error={error}
      preferredService={preferredService}
      onCreateClub={() => navigate("/clubs/new")}
      onOpenClub={(id) => navigate(`/clubs/${id}`)}
      showWelcomeGuide={showWelcomeGuide}
      onDismissWelcomeGuide={dismissWelcomeGuide}
      onCreateClubFromGuide={handleCreateClubFromGuide}
      onReopenWelcomeGuide={() => setShowWelcomeGuide(true)}
    />
  );
}
