import { type FormEvent, useState } from "react";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

type EmailEntryScreenProps = {
  onSubmit: (email: string) => void;
  submitting: boolean;
  error?: string | null;
};

export function EmailEntryScreen({ onSubmit, submitting, error }: EmailEntryScreenProps) {
  const [email, setEmail] = useState("");

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
      </div>
    </main>
  );
}
