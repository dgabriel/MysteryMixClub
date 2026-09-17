import { useState } from "react";
import { Navigate, useNavigate } from "react-router";
import { OnboardingScreen } from "./OnboardingScreen";
import { VerifyScreen } from "./VerifyScreen";
import { acceptTerms } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { nativePushAvailable, pushPermissionStatus, requestPushPermissionAndRegister } from "../ios/push";

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
      // Auto-prompt for push right after onboarding (MysteryMixClub-4vii.27,
      // IOS-04) -- the first moment the user has an account and has seen
      // what the app is, before they've necessarily joined/seen a specific
      // club yet. Only when the prompt hasn't been shown before: iOS shows
      // the real system dialog exactly once, so re-asking after a denial
      // would just silently no-op anyway -- checking first avoids a pointless
      // call and keeps this from ever masking the manual "enable
      // notifications" path in Profile as the only way back in after a deny.
      if (nativePushAvailable() && (await pushPermissionStatus()) === "prompt") {
        void requestPushPermissionAndRegister();
      }
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
