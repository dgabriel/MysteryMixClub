import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../components/Button";
import { TextField } from "../components/TextField";
import { ConcentricRings } from "../components/ConcentricRings";

type OnboardingScreenProps = {
  /** True for a brand-new user who hasn't set a display name yet. */
  needsDisplayName: boolean;
  /** True whenever the Terms of Service / Privacy Policy haven't been
   *  accepted yet (MYS-183) — covers both a brand-new user and an
   *  already-onboarded user who predates the consent requirement. */
  needsConsent: boolean;
  onSubmit: (displayName: string | undefined) => void;
  submitting: boolean;
  error?: string | null;
};

export function OnboardingScreen({
  needsDisplayName,
  needsConsent,
  onSubmit,
  submitting,
  error,
}: OnboardingScreenProps) {
  const [displayName, setDisplayName] = useState("");
  const [agreed, setAgreed] = useState(false);

  const trimmedName = displayName.trim();
  const canSubmit = (!needsDisplayName || trimmedName.length > 0) && (!needsConsent || agreed);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(needsDisplayName ? trimmedName : undefined);
  }

  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm">
        {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">
          {needsDisplayName ? "one more thing" : "one more thing before you're back in"}
        </h1>
        <p className="mt-2 text-center font-mono text-[13px] font-light text-muted">
          {needsDisplayName
            ? "choose a display name your friends will recognize."
            : "we've published a terms of service and privacy policy — please review and accept to continue."}
        </p>

        <form onSubmit={handleSubmit} className="mt-10 space-y-8">
          {needsDisplayName ? (
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
          ) : null}

          {needsConsent ? (
            <div>
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  name="accept-terms"
                  checked={agreed}
                  onChange={(e) => setAgreed(e.target.checked)}
                  disabled={submitting}
                  className="mt-0.5 h-4 w-4 rounded-[2px] border border-ink accent-sage"
                />
                <span className="font-mono text-[11px] text-ink">
                  i agree to the{" "}
                  <Link
                    to="/terms"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sage underline underline-offset-[3px] hover:text-ink"
                  >
                    terms of service
                  </Link>{" "}
                  and{" "}
                  <Link
                    to="/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sage underline underline-offset-[3px] hover:text-ink"
                  >
                    privacy policy
                  </Link>
                </span>
              </label>
            </div>
          ) : null}

          {error ? (
            <p role="alert" className="font-mono text-[11px] text-ink">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={submitting || !canSubmit} className="w-full">
            {submitting ? "saving…" : "continue"}
          </Button>
        </form>
      </div>
    </main>
  );
}
