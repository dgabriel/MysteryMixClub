import { type FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";
import { FormError } from "../components/FormError";
import { TextField } from "../components/TextField";
import { VerifyScreen } from "./VerifyScreen";
import {
  ApiError,
  PASSWORD_MAX_LENGTH,
  PASSWORD_MIN_LENGTH,
  resetPassword,
} from "../services/api";

/**
 * Landing route for the emailed password-reset link
 * (/auth/reset-password?token=...). Unlike /auth/verify this can't act on the
 * token alone — a reset needs a new password too — so the token is read on mount
 * and held until the user submits one. A spent, expired, or missing token shows
 * the same calm link-failed state as magic-link verification.
 *
 * No session comes back: the reset invalidates every existing session, so the
 * user signs in again afterwards.
 */
export function ResetPasswordRoute() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [state, setState] = useState<"form" | "done" | "error">(token ? "form" : "error");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setPasswordError(null);
    setConfirmError(null);
    setFormError(null);

    if (!password) {
      setPasswordError("enter a new password.");
      return;
    }
    if (password.length < PASSWORD_MIN_LENGTH) {
      setPasswordError(`use at least ${PASSWORD_MIN_LENGTH} characters.`);
      return;
    }
    if (password.length > PASSWORD_MAX_LENGTH) {
      setPasswordError(`use ${PASSWORD_MAX_LENGTH} characters or fewer.`);
      return;
    }
    if (confirm !== password) {
      setConfirmError("these don't match.");
      return;
    }

    setSubmitting(true);
    try {
      await resetPassword(token, password);
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // The link is spent or expired — nothing about the password itself.
        setState("error");
      } else {
        // A dropped connection or a server fault. Screen-level, never a field
        // error: the request never landed, so the password isn't the problem.
        setFormError("couldn't save that right now. try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (state === "error") {
    return (
      <VerifyScreen state="error" onBackToLogin={() => navigate("/login", { replace: true })} />
    );
  }

  if (state === "done") {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
        <div className="w-full max-w-sm text-center">
          <ConcentricRings size={72} className="mx-auto" />
          <h1 className="mt-8 font-serif text-[28px] leading-tight">password updated</h1>
          <p className="mt-4 font-mono text-[13px] font-light text-muted">
            you&apos;ve been signed out everywhere. sign in with your new password.
          </p>
          <div className="mt-10">
            <Button type="button" onClick={() => navigate("/login", { replace: true })}>
              sign in
            </Button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm">
        {/* No Rust accent on the motif: this screen shows form validation
            errors, which are the screen's Rust (ADR 0004). */}
        <ConcentricRings size={72} className="mx-auto" />
        <h1 className="mt-8 text-center font-serif text-[28px] leading-tight">
          set a new password
        </h1>

        <form onSubmit={handleSubmit} noValidate className="mt-10 space-y-8">
          <div>
            <TextField
              id="new-password"
              label="new password"
              type="password"
              name="new-password"
              autoComplete="new-password"
              revealToggle
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
              error={passwordError}
            />
            {passwordError ? null : (
              <p className="mt-2 font-mono text-[11px] font-light text-muted">
                {PASSWORD_MIN_LENGTH} characters or more.
              </p>
            )}
          </div>

          <TextField
            id="confirm-password"
            label="confirm password"
            type="password"
            name="confirm-password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={submitting}
            error={confirmError}
          />

          {formError ? <FormError>{formError}</FormError> : null}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "saving…" : "save password"}
          </Button>
        </form>
      </div>
    </main>
  );
}
