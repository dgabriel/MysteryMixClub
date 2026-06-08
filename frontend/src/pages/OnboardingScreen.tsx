import { type FormEvent, useState } from "react";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

type OnboardingScreenProps = {
  onSubmit: (displayName: string) => void;
  submitting: boolean;
  error?: string | null;
};

export function OnboardingScreen({ onSubmit, submitting, error }: OnboardingScreenProps) {
  const [displayName, setDisplayName] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = displayName.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm">
        {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">one more thing</h1>
        <p className="mt-2 text-center font-mono text-[13px] font-light text-muted">
          choose a display name your friends will recognize.
        </p>

        <form onSubmit={handleSubmit} className="mt-10 space-y-8">
          <TextField
            id="display-name"
            label="display name"
            name="display-name"
            autoComplete="nickname"
            placeholder="what should we call you?"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={submitting}
            aria-invalid={error ? true : undefined}
          />

          {error ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "saving…" : "continue"}
          </Button>
        </form>
      </div>
    </main>
  );
}
