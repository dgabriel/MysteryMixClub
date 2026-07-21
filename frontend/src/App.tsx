import { Navigate, RouterProvider, createBrowserRouter, useParams } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { AboutRoute } from "./pages/AboutRoute";
import { TermsRoute } from "./pages/TermsRoute";
import { PrivacyRoute } from "./pages/PrivacyRoute";
import { FaqRoute } from "./pages/FaqRoute";
import { VerifyRoute } from "./pages/VerifyRoute";
import { HomeRoute } from "./pages/HomeRoute";
import { OnboardingRoute } from "./pages/OnboardingRoute";
import { CreateClubRoute } from "./pages/CreateClubRoute";
import { ClubHomeRoute } from "./pages/ClubHomeRoute";
import { MixDetailRoute } from "./pages/MixDetailRoute";
import { JoinClubRoute } from "./pages/JoinClubRoute";
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
 *   /terms         → public Terms of Service (MYS-183); linked from /login,
 *                    TopNav, and the onboarding/consent gate
 *   /privacy       → public Privacy Policy (MYS-183); linked from /login,
 *                    TopNav, and the onboarding/consent gate
 *   /faq           → public FAQ (MYS-216); linked from /login and TopNav
 *
 *   Authed shell (ProtectedRoute + AuthedLayout, which renders the shared TopNav):
 *     /home        → My Clubs landing
 *     /clubs/:id   → club home (mystery mixes, members, invite, organizer edit)
 *     /mixes/:id   → mystery-mix detail (submit / playlist / reveal); shows the
 *                    nav's back link
 *     /profile     → edit display name + archived (completed) clubs
 *     /admin       → platform-admin only (self-guards non-admins → /home)
 *
 *   /clubs/new     → protected but OUTSIDE the nav shell — a focused create form
 *                    with its own cancel affordance (not in the nav's screen set).
 *
 *   /leagues/:id, /rounds/:id, /leagues/new → PERMANENT redirects to the club/mix
 *                    equivalents (MYS-192). Notification emails sent before the
 *                    rename embed /leagues/{id} links forever — never remove these.
 *   /invite/:token → public; invite preview + join. The shareable link an
 *                    organizer hands out ({app_base_url}/invite/{token}).
 *   /join/:token   → public; legacy alias for /invite/:token (in-flight links).
 *                    Both self-guard the unauthenticated case via the stored
 *                    pendingInvitePath.
 *   *              → redirect to /login
 *
 * createBrowserRouter (data router) is required for useBlocker support.
 */

/** Param-preserving redirect for the pre-rename URL shapes (league→club,
 *  round→mix). Old notification emails link these paths forever, so the
 *  redirects are permanent — never remove (MYS-192). */
function LegacyPathRedirect({ prefix }: { prefix: "clubs" | "mixes" }) {
  const { id } = useParams();
  return <Navigate to={`/${prefix}/${id}`} replace />;
}

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginRoute /> },
  { path: "/about", element: <AboutRoute /> },
  { path: "/terms", element: <TermsRoute /> },
  { path: "/privacy", element: <PrivacyRoute /> },
  { path: "/faq", element: <FaqRoute /> },
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
      { path: "/clubs/:id", element: <ClubHomeRoute /> },
      { path: "/mixes/:id", element: <MixDetailRoute /> },
      // Permanent legacy redirects — old emails link these shapes forever.
      { path: "/leagues/:id", element: <LegacyPathRedirect prefix="clubs" /> },
      { path: "/rounds/:id", element: <LegacyPathRedirect prefix="mixes" /> },
      { path: "/profile", element: <ProfileRoute /> },
      { path: "/admin", element: <AdminRoute /> },
    ],
  },

  // Authed but outside the nav shell — a focused create form.
  {
    path: "/clubs/new",
    element: (
      <ProtectedRoute>
        <CreateClubRoute />
      </ProtectedRoute>
    ),
  },
  { path: "/leagues/new", element: <Navigate to="/clubs/new" replace /> },

  { path: "/invite/:token", element: <JoinClubRoute /> },
  { path: "/join/:token", element: <JoinClubRoute /> },
  { path: "*", element: <Navigate to="/login" replace /> },
]);

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
