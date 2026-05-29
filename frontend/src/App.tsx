import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./hooks/useAuth";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginRoute } from "./pages/LoginRoute";
import { VerifyRoute } from "./pages/VerifyRoute";
import { HomeRoute } from "./pages/HomeRoute";

/**
 * Route map:
 *   /             → redirect to /login
 *   /login        → magic-link request flow (EmailEntry → CheckEmail)
 *   /auth/verify  → magic-link landing; verifies token, then → /home
 *   /home         → protected; the signed-in shell
 *   *             → redirect to /login
 */
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/auth/verify" element={<VerifyRoute />} />
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <HomeRoute />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
