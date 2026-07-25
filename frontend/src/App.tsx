import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, RouterProvider, createBrowserRouter, useParams } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { AuthedLayout } from "./components/AuthedLayout";
import { RouteFallback } from "./components/RouteFallback";

// Lazy-loaded (MYS-240): everything except the /login entry point itself,
// which is the page Lighthouse audits and the one that must not wait on
// chunks it doesn't need. Cuts unused JS out of that first bundle.
const AboutRoute = lazy(() => import("./pages/AboutRoute").then((m) => ({ default: m.AboutRoute })));
const TermsRoute = lazy(() => import("./pages/TermsRoute").then((m) => ({ default: m.TermsRoute })));
const PrivacyRoute = lazy(() =>
  import("./pages/PrivacyRoute").then((m) => ({ default: m.PrivacyRoute })),
);
const HelpRoute = lazy(() => import("./pages/HelpRoute").then((m) => ({ default: m.HelpRoute })));
const VerifyRoute = lazy(() =>
  import("./pages/VerifyRoute").then((m) => ({ default: m.VerifyRoute })),
);
const HomeRoute = lazy(() => import("./pages/HomeRoute").then((m) => ({ default: m.HomeRoute })));
const OnboardingRoute = lazy(() =>
  import("./pages/OnboardingRoute").then((m) => ({ default: m.OnboardingRoute })),
);
const CreateClubRoute = lazy(() =>
  import("./pages/CreateClubRoute").then((m) => ({ default: m.CreateClubRoute })),
);
const ClubHomeRoute = lazy(() =>
  import("./pages/ClubHomeRoute").then((m) => ({ default: m.ClubHomeRoute })),
);
const MixDetailRoute = lazy(() =>
  import("./pages/MixDetailRoute").then((m) => ({ default: m.MixDetailRoute })),
);
const JoinClubRoute = lazy(() =>
  import("./pages/JoinClubRoute").then((m) => ({ default: m.JoinClubRoute })),
);
const AdminRoute = lazy(() => import("./pages/AdminRoute").then((m) => ({ default: m.AdminRoute })));
const ProfileRoute = lazy(() =>
  import("./pages/ProfileRoute").then((m) => ({ default: m.ProfileRoute })),
);

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
 *   /help          → public help/FAQ (MYS-222); linked from /login, TopNav, and
 *                    context-help "?" icons elsewhere in the app (HelpLink.tsx)
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

/** Wraps a lazy-loaded route element in its own Suspense boundary (MYS-240) so
 *  only that route's content shows the loading motif — a lazy child inside
 *  AuthedLayout never unmounts the persistent TopNav around it. */
function withSuspense(element: ReactNode) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>;
}

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/login" replace /> },
  { path: "/login", element: <LoginRoute /> },
  { path: "/about", element: withSuspense(<AboutRoute />) },
  { path: "/terms", element: withSuspense(<TermsRoute />) },
  { path: "/privacy", element: withSuspense(<PrivacyRoute />) },
  { path: "/help", element: withSuspense(<HelpRoute />) },
  { path: "/auth/verify", element: withSuspense(<VerifyRoute />) },
  { path: "/onboarding", element: withSuspense(<OnboardingRoute />) },

  // Authed screens share the TopNav via AuthedLayout (mounted once).
  {
    element: (
      <ProtectedRoute>
        <AuthedLayout />
      </ProtectedRoute>
    ),
    children: [
      { path: "/home", element: withSuspense(<HomeRoute />) },
      { path: "/clubs/:id", element: withSuspense(<ClubHomeRoute />) },
      { path: "/mixes/:id", element: withSuspense(<MixDetailRoute />) },
      // Permanent legacy redirects — old emails link these shapes forever.
      { path: "/leagues/:id", element: <LegacyPathRedirect prefix="clubs" /> },
      { path: "/rounds/:id", element: <LegacyPathRedirect prefix="mixes" /> },
      { path: "/profile", element: withSuspense(<ProfileRoute />) },
      { path: "/admin", element: withSuspense(<AdminRoute />) },
    ],
  },

  // Authed but outside the nav shell — a focused create form.
  {
    path: "/clubs/new",
    element: <ProtectedRoute>{withSuspense(<CreateClubRoute />)}</ProtectedRoute>,
  },
  { path: "/leagues/new", element: <Navigate to="/clubs/new" replace /> },

  { path: "/invite/:token", element: withSuspense(<JoinClubRoute />) },
  { path: "/join/:token", element: withSuspense(<JoinClubRoute />) },
  { path: "*", element: <Navigate to="/login" replace /> },
]);

export default function App() {
  return (
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
