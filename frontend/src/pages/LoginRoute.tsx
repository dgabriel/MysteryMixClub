import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { EmailEntryScreen, type LoginMode } from "./EmailEntryScreen";
import { CheckEmailScreen } from "./CheckEmailScreen";
import {
  ApiError,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  forgotPassword,
  googleLoginUrl,
  login,
  register,
  requestMagicLink,
} from "../services/api";
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

const INVITE_REQUIRED_COPY = "you need an invite to create an account";

/** Calm copy for the outcome flag Google's callback redirects back with. `ok`
 *  needs nothing — the on-mount silent refresh picks the session up from the
 *  cookie and the authenticated redirect below fires (MYS-92). */
function googleErrorCopy(outcome: string | null): string | null {
  switch (outcome) {
    case null:
    case "ok":
      return null;
    case "denied":
      return "google sign-in was cancelled.";
    case "email_unverified":
      return "verify your email with google, then try again.";
    case "invite_required":
      return INVITE_REQUIRED_COPY;
    case "at_capacity":
      return "MysteryMixClub is at capacity right now.";
    case "club_full":
      return "that club is full.";
    default:
      return "that sign-in didn't work. try another way.";
  }
}

/**
 * Login flow container. Drives EmailEntryScreen → CheckEmailScreen and owns the
 * three sign-in methods (ADR 0007): magic link, email + password (sign in,
 * register, forgot), and the Google redirect's return leg.
 */
export function LoginRoute() {
  const { status, setAccessToken } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [mode, setMode] = useState<LoginMode>("magic");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Google's outcome is held apart from `error` rather than folded into it: the
  // two share wording in places (invite_required, at_capacity, club_full) but
  // get different treatment, because the split is by source, not by text. Read
  // once at mount; the param itself is stripped from the URL below.
  const [googleError, setGoogleError] = useState<string | null>(() =>
    googleErrorCopy(searchParams.get("google")),
  );
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devLink, setDevLink] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [resetDevLink, setResetDevLink] = useState<string | null>(null);

  // Strip ?google= as soon as it has been read. Left in place it would survive
  // a reload, a back-navigation, or a bookmark, and resurface a stale outcome on
  // an unrelated later visit. Skipped once authenticated, where a redirect to
  // /home is already in flight.
  useEffect(() => {
    if (status === "authenticated" || !searchParams.has("google")) return;
    const next = new URLSearchParams(searchParams);
    next.delete("google");
    setSearchParams(next, { replace: true });
  }, [status, searchParams, setSearchParams]);

  function clearFeedback() {
    setError(null);
    setGoogleError(null);
    setPasswordError(null);
    setDevLink(null);
    setResetNotice(null);
    setResetDevLink(null);
  }

  async function handleSubmit(email: string) {
    setSubmitting(true);
    setError(null);
    setGoogleError(null);
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

  async function handlePasswordSignIn(email: string, password: string) {
    setSubmitting(true);
    clearFeedback();
    try {
      const { access_token } = await login(email, password);
      setAccessToken(access_token);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // One uniform message for every failure mode — never narrow it.
        setPasswordError(err.message);
      } else if (err instanceof ApiError && err.status === 429) {
        setError(err.message);
      } else {
        setError("that didn't work. try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegister(email: string, password: string) {
    clearFeedback();
    if (password.length < PASSWORD_MIN_LENGTH) {
      setPasswordError(`use at least ${PASSWORD_MIN_LENGTH} characters.`);
      return;
    }
    if (password.length > PASSWORD_MAX_LENGTH) {
      setPasswordError(`use ${PASSWORD_MAX_LENGTH} characters or fewer.`);
      return;
    }
    // Registration is invite-gated and the backend requires the token outright,
    // so with nothing stashed there is no request worth making — say what the
    // server would have said.
    const inviteToken = readPendingInviteToken();
    if (!inviteToken) {
      setError(INVITE_REQUIRED_COPY);
      return;
    }

    setSubmitting(true);
    try {
      const { access_token } = await register(email, password, inviteToken);
      setAccessToken(access_token);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 409)) {
        // Both details are already calm ("you need an invite to create an
        // account" / "an account already exists for this email — sign in
        // instead"); shown as-is.
        setError(err.message);
      } else {
        setError("that didn't work. try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleForgotPassword(email: string) {
    setSubmitting(true);
    clearFeedback();
    try {
      const { devToken } = await forgotPassword(email);
      // Neutral either way — a 200 says nothing about whether the address has a
      // password, so this never claims an email was sent.
      setResetNotice("if that email has a password set, a reset link is on its way.");
      if (devToken) {
        setResetDevLink(`/auth/reset-password?token=${encodeURIComponent(devToken)}`);
      }
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? err.message
          : "that didn't work. try again.",
      );
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

  const pendingInvite = readPendingInviteToken();

  return (
    <EmailEntryScreen
      onSubmit={handleSubmit}
      submitting={submitting}
      error={error}
      devLink={devLink}
      mode={mode}
      onModeChange={(next) => {
        clearFeedback();
        setMode(next);
      }}
      onPasswordSignIn={handlePasswordSignIn}
      onRegister={handleRegister}
      onForgotPassword={handleForgotPassword}
      canRegister={pendingInvite !== null}
      passwordError={passwordError}
      googleError={googleError}
      resetNotice={resetNotice}
      resetDevLink={resetDevLink}
      googleUrl={googleLoginUrl(pendingInvite)}
    />
  );
}
