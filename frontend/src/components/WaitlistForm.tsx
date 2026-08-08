import { type FormEvent, useState } from "react";
import { ApiError, joinWaitlist } from "../services/api";
import { Button } from "./Button";
import { FormError } from "./FormError";
import { TextField } from "./TextField";

/**
 * Public waitlist join form (MYS-215, temporary pre-launch flow) — replaces
 * the "email us for an invite" copy on the login page while the waitlist
 * flag is on. The caller (EmailEntryScreen) owns the enabled/disabled check
 * and only mounts this when the waitlist is actually on, so this component
 * assumes it should render and just handles the join itself.
 *
 * The join failures are form validation, so they render through the shared
 * `FormError` in `destructive-text` (ADR 0004) rather than as plain copy — form
 * errors are their own color category and take nothing from the accent.
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
      <p className="mt-10 text-center text-sm leading-[1.72] text-muted-foreground">
        you&apos;re on the waitlist. we&apos;ll email you when a spot opens up.
      </p>
    );
  }

  return (
    <div className="mt-10 text-center">
      <p className="text-sm leading-[1.72] text-muted-foreground">
        no invite yet? join the waitlist.
      </p>
      <form onSubmit={handleSubmit} noValidate className="mt-3 flex items-end justify-center gap-3">
        <div className="w-full max-w-[220px] text-left">
          <TextField
            id="waitlist-email"
            // Not just "email": this sits on the same page as the sign-in form's
            // own email field, and two identically-labelled fields read as one.
            label="your email"
            type="email"
            name="email"
            autoComplete="email"
            inputMode="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={submitting}
            // Underline-only: `invalid` switches the rule to `destructive-text`
            // so the field itself shows the state, not just the message below
            // the form. `error` is not used here because the message is rendered
            // outside the form, centred. The rendered `aria-invalid` is
            // unchanged either way — TextField emits `true` when `invalid` is
            // set and falls through to the explicit prop below when it isn't.
            invalid={Boolean(error)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "waitlist-email-error" : undefined}
          />
        </div>
        <Button type="submit" variant="ghost" disabled={submitting}>
          {submitting ? "joining…" : "join"}
        </Button>
      </form>
      {error ? (
        // FormError owns the `role="alert"`, the id, and the warning icon; the
        // wrapper only re-centres it inside this centred block, since the
        // primitive takes no className.
        <div className="mt-2 flex justify-center">
          <FormError id="waitlist-email-error">{error}</FormError>
        </div>
      ) : null}
    </div>
  );
}
