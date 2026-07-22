import { useState } from "react";
import { Navigate } from "react-router-dom";
import { EmailEntryScreen } from "./EmailEntryScreen";
import { CheckEmailScreen } from "./CheckEmailScreen";
import { requestMagicLink } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Pull the invite token out of a stashed pending-invite path. The join flow
 * stores the full path the visitor landed on (e.g. "/invite/<token>" or the
 * legacy "/join/<token>"); we only need the trailing token to thread through
 * sign-in so a new account can be gated + auto-joined. Returns null when there
 * is no pending invite (ordinary sign-in by an existing user).
 */
function readPendingInviteToken(): string | null {
  const pending = localStorage.getItem("pendingInvitePath");
  if (!pending) return null;
  const match = pending.match(/^\/(?:invite|join)\/([^/?#]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Login flow container. Drives EmailEntryScreen → CheckEmailScreen.
 * Wires the presentational screens via their documented props only.
 */
export function LoginRoute() {
  const { status } = useAuth();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);

  async function handleSubmit(email: string) {
    setSubmitting(true);
    setError(null);
    setDevLink(null);
    try {
      // When arriving from an invite link, carry its token so the backend can
      // gate signup on it and auto-join the club on verify.
      const inviteToken = readPendingInviteToken();
      const { devToken } = await requestMagicLink(email, inviteToken);
      if (devToken) {
        // Dev/staging only: show a clickable relative sign-in link in place of
        // the emailed one (which isn't deliverable in those environments). The
        // invite token rides along as `&invite=` so verify mirrors the email link.
        const params = new URLSearchParams({ token: devToken });
        if (inviteToken) params.set("invite", inviteToken);
        setDevLink(`/auth/verify?${params.toString()}`);
      } else {
        setSentTo(email);
      }
    } catch {
      setError("that didn't work. check the address and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  // An already-authenticated user has no business on the login form — e.g. after
  // returning from an external OAuth flow that lands on a route which funnels
  // here. Bounce them home (MYS-92). /home cascades to /onboarding if needed.
  if (status === "authenticated") {
    return <Navigate to="/home" replace />;
  }

  if (sentTo) {
    return <CheckEmailScreen email={sentTo} onBack={() => setSentTo(null)} />;
  }

  return (
    <EmailEntryScreen
      onSubmit={handleSubmit}
      submitting={submitting}
      error={error}
      devLink={devLink}
    />
  );
}
