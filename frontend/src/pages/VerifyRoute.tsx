import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { VerifyScreen } from "./VerifyScreen";
import { verifyToken } from "../services/api";
import { useAuth } from "../hooks/useAuth";

/**
 * Handles the magic-link landing route (/auth/verify?token=...). Reads the
 * token from the query string on mount, verifies it, stores the access token,
 * and routes to /home. On failure shows the error state.
 */
export function VerifyRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { setAccessToken } = useAuth();
  const [state, setState] = useState<"verifying" | "error">("verifying");
  const didRun = useRef(false);

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke; a magic-link token is
    // single-use, so we must only call verify once.
    if (didRun.current) return;
    didRun.current = true;

    const token = searchParams.get("token");
    if (!token) {
      setState("error");
      return;
    }

    let active = true;
    void (async () => {
      try {
        const { access_token } = await verifyToken(token);
        if (!active) return;
        setAccessToken(access_token);
        navigate("/home", { replace: true });
      } catch {
        if (active) setState("error");
      }
    })();

    return () => {
      active = false;
    };
  }, [searchParams, navigate, setAccessToken]);

  return (
    <VerifyScreen state={state} onBackToLogin={() => navigate("/login", { replace: true })} />
  );
}
