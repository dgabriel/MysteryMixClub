import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { OnboardingScreen } from "./OnboardingScreen";
import { VerifyScreen } from "./VerifyScreen";
import { acceptTerms } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * First-login / consent onboarding route. Captures the display name for
 * users whose profile still carries the empty-string sentinel, and captures
 * Terms of Service / Privacy Policy acceptance (MYS-183) whenever it's
 * missing — which covers both a brand-new user and an already-onboarded user
 * who predates the consent requirement (a live beta user with no prior
 * acceptance record). Guards mirror ProtectedRoute so the two routes can't
 * bounce a user back and forth:
 *  - still loading auth or profile → the loading motif.
 *  - unauthenticated → /login.
 *  - display name set and terms accepted → /home (nothing to do here).
 */
export function OnboardingRoute() {
  const navigate = useNavigate();
  const { status, profileStatus, needsOnboarding, displayName, tosAccepted, applyDisplayName, applyTosAccepted } =
    useAuth();
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

  const needsDisplayName = displayName === "";
  const needsConsent = !tosAccepted;

  async function handleSubmit(name: string | undefined) {
    setSubmitting(true);
    setError(null);
    try {
      const profile = await acceptTerms(name);
      applyDisplayName(profile.display_name);
      applyTosAccepted();
      navigate("/home", { replace: true });
    } catch {
      // acceptTerms throws ApiError on a non-2xx response (and the wrapper
      // already tried a silent refresh). Either way it's a save failure — keep
      // the user on the screen with a calm, retryable message.
      setError("that didn't save. try again.");
      setSubmitting(false);
    }
  }

  return (
    <OnboardingScreen
      needsDisplayName={needsDisplayName}
      needsConsent={needsConsent}
      onSubmit={handleSubmit}
      submitting={submitting}
      error={error}
    />
  );
}
