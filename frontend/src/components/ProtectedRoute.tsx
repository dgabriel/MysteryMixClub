import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { VerifyScreen } from "../pages/VerifyScreen";

/**
 * Gates protected routes on auth status.
 *  - "loading": the on-mount silent refresh is in flight. Render the neutral
 *    rotating-motif loading state so a reopened PWA doesn't flash the login
 *    screen before the session is restored.
 *  - "unauthenticated": redirect to /login.
 *  - "authenticated": render the protected content.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();

  if (status === "loading") {
    return <VerifyScreen state="verifying" />;
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}
