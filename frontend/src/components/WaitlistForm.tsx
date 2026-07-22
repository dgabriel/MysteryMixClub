import { type FormEvent, useState } from "react";
import { ApiError, joinWaitlist } from "../services/api";
import { Button } from "./Button";
import { TextField } from "./TextField";

/**
 * Public waitlist join form (MYS-215, temporary pre-launch flow) — replaces
 * the "email us for an invite" copy on the login page while the waitlist
 * flag is on. The caller (EmailEntryScreen) owns the enabled/disabled check
 * and only mounts this when the waitlist is actually on, so this component
 * assumes it should render and just handles the join itself.
 *
 * Stays in the Sage/Ink/Muted family — no Rust: EmailEntryScreen's single
 * Rust use is already spent on the concentric-rings motif above this form.
 */
export function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await joinWaitlist(trimmed);
      setJoined(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("that email is already on the waitlist.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("that doesn't look like an email.");
      } else {
        setError("couldn't join the waitlist. try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (joined) {
    return (
      <p className="mt-10 text-center font-mono text-[11px] font-light text-muted">
        you&apos;re on the waitlist. we&apos;ll email you when a spot opens up.
      </p>
    );
  }

  return (
    <div className="mt-10 text-center">
      <p className="font-mono text-[11px] font-light text-muted">no invite yet? join the waitlist.</p>
      <form onSubmit={handleSubmit} className="mt-3 flex items-end justify-center gap-3">
        <div className="w-full max-w-[220px] text-left">
          <TextField
            id="waitlist-email"
            label="email"
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            aria-invalid={error ? true : undefined}
          />
        </div>
        <Button type="submit" variant="ghost" disabled={submitting}>
          {submitting ? "joining…" : "join"}
        </Button>
      </form>
      {error ? (
        <p role="alert" className="mt-2 font-mono text-[11px] text-ink">
          {error}
        </p>
      ) : null}
    </div>
  );
}
