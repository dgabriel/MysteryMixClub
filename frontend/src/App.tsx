import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { AboutRoute } from "./pages/AboutRoute";
import { VerifyRoute } from "./pages/VerifyRoute";
import { HomeRoute } from "./pages/HomeRoute";
import { OnboardingRoute } from "./pages/OnboardingRoute";
import { CreateLeagueRoute } from "./pages/CreateLeagueRoute";
import { LeagueHomeRoute } from "./pages/LeagueHomeRoute";
import { RoundDetailRoute } from "./pages/RoundDetailRoute";
import { JoinLeagueRoute } from "./pages/JoinLeagueRoute";
import { AdminRoute } from "./pages/AdminRoute";
import { ProfileRoute } from "./pages/ProfileRoute";
import { AuthedLayout } from "./components/AuthedLayout";

/**
 * Route map:
 *   /              → redirect to /login
 *   /login         → magic-link request flow (EmailEntry → CheckEmail)
 *   /auth/verify   → magic-link landing; verifies token, then → /home
 *   /onboarding    → first-login display-name capture (self-guarded; bounces
 *                    unauthenticated → /login, already-onboarded → /home)
 *   /about         → public static about page (MYS-155); linked from /login
 *
 *   Authed shell (ProtectedRoute + AuthedLayout, which renders the shared TopNav):
 *     /home        → My Leagues landing
 *     /leagues/:id → league home (rounds, members, invite, organizer edit)
 *     /rounds/:id  → round detail (submit / playlist / reveal); shows the
 *                    nav's "← league" back link
 *     /profile     → edit display name + archived (completed) leagues
 *     /admin       → platform-admin only (self-guards non-admins → /home)
 *
 *   /leagues/new   → protected but OUTSIDE the nav shell — a focused create form
 *                    with its own cancel affordance (not in the nav's screen set).
 *   /invite/:token → public; invite preview + join. The shareable link an
 *                    organizer hands out ({app_base_url}/invite/{token}).
 *   /join/:token   → public; legacy alias for /invite/:token (in-flight links).
 *                    Both self-guard the unauthenticated case via the stored
 *                    pendingInvitePath.
 *   *              → redirect to /login
 *
 * createBrowserRouter (data router) is required for useBlocker support.
 */
const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginRoute /> },
  { path: "/about", element: <AboutRoute /> },
  { path: "/auth/verify", element: <VerifyRoute /> },
  { path: "/onboarding", element: <OnboardingRoute /> },

  // Authed screens share the TopNav via AuthedLayout (mounted once).
  {
    element: (
      <ProtectedRoute>
        <AuthedLayout />
      </ProtectedRoute>
    ),
    children: [
      { path: "/home", element: <HomeRoute /> },
      { path: "/leagues/:id", element: <LeagueHomeRoute /> },
      { path: "/rounds/:id", element: <RoundDetailRoute /> },
      { path: "/profile", element: <ProfileRoute /> },
      { path: "/admin", element: <AdminRoute /> },
    ],
  },

  // Authed but outside the nav shell — a focused create form.
  {
    path: "/leagues/new",
    element: (
      <ProtectedRoute>
        <CreateLeagueRoute />
      </ProtectedRoute>
    ),
  },

  { path: "/invite/:token", element: <JoinLeagueRoute /> },
  { path: "/join/:token", element: <JoinLeagueRoute /> },
  { path: "*", element: <Navigate to="/login" replace /> },
]);

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
