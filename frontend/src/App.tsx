import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { VerifyRoute } from "./pages/VerifyRoute";
import { HomeRoute } from "./pages/HomeRoute";
import { OnboardingRoute } from "./pages/OnboardingRoute";
import { CreateLeagueRoute } from "./pages/CreateLeagueRoute";
import { LeagueHomeRoute } from "./pages/LeagueHomeRoute";
import { JoinLeagueRoute } from "./pages/JoinLeagueRoute";

/**
 * Route map:
 *   /              → redirect to /login
 *   /login         → magic-link request flow (EmailEntry → CheckEmail)
 *   /auth/verify   → magic-link landing; verifies token, then → /home
 *   /onboarding    → first-login display-name capture (self-guarded; bounces
 *                    unauthenticated → /login, already-onboarded → /home)
 *   /home          → protected; My Leagues landing
 *   /leagues/new   → protected; create a league
 *   /leagues/:id   → protected; league home (members, invite, organizer edit)
 *   /join/:token   → public; invite preview + join (self-guards the
 *                    unauthenticated case via stored pendingInvitePath)
 *   *              → redirect to /login
 */
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/auth/verify" element={<VerifyRoute />} />
          <Route path="/onboarding" element={<OnboardingRoute />} />
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <HomeRoute />
              </ProtectedRoute>
            }
          />
          <Route
            path="/leagues/new"
            element={
              <ProtectedRoute>
                <CreateLeagueRoute />
              </ProtectedRoute>
            }
          />
          <Route
            path="/leagues/:id"
            element={
              <ProtectedRoute>
                <LeagueHomeRoute />
              </ProtectedRoute>
            }
          />
          <Route path="/join/:token" element={<JoinLeagueRoute />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
