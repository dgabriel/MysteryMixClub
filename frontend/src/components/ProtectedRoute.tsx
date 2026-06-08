import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { VerifyScreen } from "../pages/VerifyScreen";

/**
 * Gates protected routes on auth status and onboarding.
 *  - "loading": the on-mount silent refresh is in flight. Render the neutral
 *    rotating-motif loading state so a reopened PWA doesn't flash the login
 *    screen before the session is restored.
 *  - "unauthenticated": redirect to /login.
 *  - authenticated but profile not yet "ready": keep showing the loading motif
 *    so we don't flash /home and then redirect to onboarding.
 *  - authenticated and onboarding still needed: redirect to /onboarding.
 *  - "authenticated" and onboarded: render the protected content.
 */
export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status, profileStatus, needsOnboarding } = useAuth();

  if (status === "loading") {
    return <VerifyScreen state="verifying" />;
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  if (profileStatus !== "ready") {
    return <VerifyScreen state="verifying" />;
  }

  if (needsOnboarding) {
    return <Navigate to="/onboarding" replace />;
  }

  return <>{children}</>;
}
