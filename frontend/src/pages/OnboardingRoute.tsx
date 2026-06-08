import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { OnboardingScreen } from "./OnboardingScreen";
import { VerifyScreen } from "./VerifyScreen";
import { updateDisplayName } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * First-login onboarding route. Captures the display name for users whose
 * profile still carries the empty-string sentinel. Guards mirror ProtectedRoute
 * so the two routes can't bounce a user back and forth:
 *  - still loading auth or profile → the loading motif.
 *  - unauthenticated → /login.
 *  - already onboarded → /home (nothing to do here).
 */
export function OnboardingRoute() {
  const navigate = useNavigate();
  const { status, profileStatus, needsOnboarding, applyDisplayName } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "loading" || (status === "authenticated" && profileStatus !== "ready")) {
    return <VerifyScreen state="verifying" />;
  }

  if (status === "unauthenticated") {
    return <Navigate to="/login" replace />;
  }

  if (!needsOnboarding) {
    return <Navigate to="/home" replace />;
  }

  async function handleSubmit(name: string) {
    setSubmitting(true);
    setError(null);
    try {
      const profile = await updateDisplayName(name);
      applyDisplayName(profile.display_name);
      navigate("/home", { replace: true });
    } catch {
      // updateDisplayName throws ApiError on a non-2xx response (and the wrapper
      // already tried a silent refresh). Either way it's a save failure — keep
      // the user on the screen with a calm, retryable message.
      setError("that didn't save. try again.");
      setSubmitting(false);
    }
  }

  return <OnboardingScreen onSubmit={handleSubmit} submitting={submitting} error={error} />;
}
