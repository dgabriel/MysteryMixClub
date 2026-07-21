import { type FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../components/Button";
import { ContactEmail } from "../components/ContactEmail";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";
import { WaitlistForm } from "../components/WaitlistForm";
import { getWaitlistEnabled } from "../services/api";

type EmailEntryScreenProps = {
  onSubmit: (email: string) => void;
  submitting: boolean;
  error?: string | null;
  /** Dev/staging only: a relative sign-in link to show below the button. */
  devLink?: string | null;
};

export function EmailEntryScreen({
  onSubmit,
  submitting,
  error,
  devLink,
}: EmailEntryScreenProps) {
  const [email, setEmail] = useState("");
  // undefined = still checking (renders neither form nor fallback copy, to
  // avoid a flash of the wrong one), null = disabled or the check failed —
  // both fall back to today's "email us" copy (fail-safe, MYS-215).
  const [waitlistEnabled, setWaitlistEnabled] = useState<boolean | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    getWaitlistEnabled()
      .then((r) => {
        if (active) setWaitlistEnabled(r.enabled);
      })
      .catch(() => {
        if (active) setWaitlistEnabled(null);
      });
    return () => {
      active = false;
    };
  }, []);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = email.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm">
        {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">
          mysterymixclub
        </h1>
        <p className="mt-2 text-center font-mono text-[13px] font-light text-muted">
          invite-only. sign in with your email.
        </p>

        <form onSubmit={handleSubmit} className="mt-10 space-y-8">
          <TextField
            id="email"
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

          {error ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "sending…" : "send sign-in link"}
          </Button>
        </form>

        {/* Below the sign-in form, not above it (MYS-215) — this is the
            secondary path for someone without an account yet, not the
            primary action on the page. */}
        {waitlistEnabled ? (
          <WaitlistForm />
        ) : waitlistEnabled === undefined ? null : (
          <p className="mt-10 text-center font-mono text-[11px] font-light text-muted">
            no invite yet?{" "}
            <ContactEmail
              user="info"
              domain="mysterymixclub.com"
              label="email us"
              className="text-ink underline underline-offset-[3px]"
            />{" "}
            to request one.
          </p>
        )}

        {/* Dev/staging convenience: a clickable sign-in link so testers don't
            need a delivered email. Styled understated (ink, not Rust — the
            screen's single Rust use is the ring dot above). */}
        {devLink ? (
          <div className="mt-8 border-t border-border pt-6">
            <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
              dev · staging only
            </p>
            <a
              href={devLink}
              className="mt-3 inline-block font-mono text-[13px] font-light text-ink underline underline-offset-[3px] break-all"
            >
              sign in with this link
            </a>
          </div>
        ) : null}

        <div className="mt-10 flex justify-center gap-4 text-center">
          <Link to="/about" className="font-mono text-[11px] text-muted hover:text-ink">
            about mysterymixclub
          </Link>
          <Link to="/terms" className="font-mono text-[11px] text-muted hover:text-ink">
            terms
          </Link>
          <Link to="/privacy" className="font-mono text-[11px] text-muted hover:text-ink">
            privacy
          </Link>
        </div>
      </div>
    </main>
  );
}
