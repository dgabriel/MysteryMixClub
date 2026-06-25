import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { VerifyScreen } from "./VerifyScreen";
import { ApiError, verifyToken } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/** Calm error copy keyed off the verify failure. A 410 means the invite link
 *  expired; a 403 carries a calm backend detail (invite-required / at-capacity)
 *  we can show verbatim; anything else falls back to the link-failed default. */
function errorCopy(err: unknown): { heading?: string; message?: string } {
  if (err instanceof ApiError) {
    if (err.status === 410) {
      return {
        heading: "this link has expired",
        message: "ask the organizer for a new one.",
      };
    }
    if (err.status === 403) {
      // e.g. "you need an invite to create an account" / "MysteryMixClub is at
      // capacity right now." — already calm, shown as-is.
      return { heading: "can’t sign you in", message: err.message };
    }
  }
  return {};
}

/**
 * Handles the magic-link landing route (/auth/verify?token=...&invite=...). Reads
 * the magic token (and an optional invite token) from the query string on mount,
 * verifies it, stores the access token, and routes to /home. On failure shows a
 * calm error — expired invite (410), invite-required / at-capacity (403), or the
 * generic link-failed state.
 */
export function VerifyRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { setAccessToken } = useAuth();
  const [state, setState] = useState<"verifying" | "error">("verifying");
  const [copy, setCopy] = useState<{ heading?: string; message?: string }>({});
  const didRun = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke; a magic-link token is
    // single-use, so we must only call verify once.
    if (didRun.current) return;
    didRun.current = true;

    const token = searchParams.get("token");
    const invite = searchParams.get("invite");
    if (!token) {
      setState("error");
      return;
    }

    // The token is single-use, so we verify exactly once (guarded by didRun
    // above). The result must always be applied — we deliberately do NOT gate it
    // on an effect-cleanup flag, because StrictMode runs cleanup before this one
    // call resolves, which would otherwise discard the only result.
    void (async () => {
      try {
        const { access_token } = await verifyToken(token, invite);
        setAccessToken(access_token);
        navigate("/home", { replace: true });
      } catch (err) {
        setCopy(errorCopy(err));
        setState("error");
      }
    })();
  }, [searchParams, navigate, setAccessToken]);

  return (
    <VerifyScreen
      state={state}
      heading={copy.heading}
      message={copy.message}
      onBackToLogin={() => navigate("/login", { replace: true })}
    />
  );
}
