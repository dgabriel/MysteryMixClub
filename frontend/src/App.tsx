import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, createBrowserRouter, useParams } from "react-router";
// RouterProvider depends on react-dom, so v7 requires it from the deep DOM
// entry point in a real browser context (react-router/dom) -- the top-level
// package export is for non-DOM contexts like tests instead.
import { RouterProvider } from "react-router/dom";
import { AuthProvider } from "./hooks/AuthProvider";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { AuthedLayout } from "./components/AuthedLayout";
import { RouteFallback } from "./components/RouteFallback";

// Lazy-loaded (MYS-240): everything except the /login entry point itself,
// which is the page Lighthouse audits and the one that must not wait on
// chunks it doesn't need. Cuts unused JS out of that first bundle.
const AboutRoute = lazy(() =>
  import("./pages/AboutRoute").then((m) => ({ default: m.AboutRoute })),
);
const TermsRoute = lazy(() =>
  import("./pages/TermsRoute").then((m) => ({ default: m.TermsRoute })),
);
const PrivacyRoute = lazy(() =>
  import("./pages/PrivacyRoute").then((m) => ({ default: m.PrivacyRoute })),
);
const HelpRoute = lazy(() => import("./pages/HelpRoute").then((m) => ({ default: m.HelpRoute })));
const VerifyRoute = lazy(() =>
  import("./pages/VerifyRoute").then((m) => ({ default: m.VerifyRoute })),
);
const ResetPasswordRoute = lazy(() =>
  import("./pages/ResetPasswordRoute").then((m) => ({ default: m.ResetPasswordRoute })),
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
const AdminRoute = lazy(() =>
  import("./pages/AdminRoute").then((m) => ({ default: m.AdminRoute })),
);
const AdminMetricsRoute = lazy(() =>
  import("./pages/AdminMetricsRoute").then((m) => ({ default: m.AdminMetricsRoute })),
);
const ProfileRoute = lazy(() =>
  import("./pages/ProfileRoute").then((m) => ({ default: m.ProfileRoute })),
);
const SubmissionHistoryRoute = lazy(() =>
  import("./pages/SubmissionHistoryRoute").then((m) => ({ default: m.SubmissionHistoryRoute })),
);

/**
 * Route map:
 *   /              → redirect to /login
 *   /login         → sign-in: magic link (EmailEntry → CheckEmail), email +
 *                    password (sign in / register / forgot), and Google's
 *                    redirect return leg (?google=<outcome>) — ADR 0007
 *   /auth/verify   → magic-link landing; verifies token, then → /home
 *   /auth/reset-password → password-reset landing; collects a new password and
 *                    submits it with the emailed token (ADR 0007)
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
 *     /profile/history → every song the caller has ever submitted, across
 *                    every club (MysteryMixClub-ps1w.1)
 *     /admin       → platform-admin only (self-guards non-admins → /home)
 *     /admin/metrics → platform-admin only; read-only platform snapshot,
 *                    self-guarded the same way as /admin
 *
 *   /clubs/new     → protected, inside the nav shell like every other authed
 *                    screen. Not in the nav's own screen set, but it keeps the
 *                    toolbar, plus its own cancel affordance back to /home.
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
  { path: "/auth/reset-password", element: withSuspense(<ResetPasswordRoute />) },
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
      { path: "/profile/history", element: withSuspense(<SubmissionHistoryRoute />) },
      { path: "/admin", element: withSuspense(<AdminRoute />) },
      { path: "/admin/metrics", element: withSuspense(<AdminMetricsRoute />) },
      // /clubs/new used to sit outside this layout as a "focused" form with no
      // nav. In practice that read as a broken page — you land on it from the
      // nav shell and the toolbar vanishes — so it joins the shell like every
      // other authed screen. Its own `cancel` still goes back to /home.
      { path: "/clubs/new", element: withSuspense(<CreateClubRoute />) },
    ],
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
