import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "../components/Button";
import { CheckmarkIcon } from "../components/CheckmarkIcon";
import { FormError } from "../components/FormError";
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
        {/* The brand mark, accented — it carries the brand on a screen that has
            no other identity placement. /onboarding is registered as a top-level
            route in App.tsx, outside the AuthedLayout children that mount
            TopNav, so this screen renders no nav mark of its own. */}
        <ConcentricRings size={72} accent className="mx-auto" />

        <h1 className="mt-8 text-center font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
          {needsDisplayName ? "one more thing" : "one more thing before you're back in"}
        </h1>
        <p className="mt-2 text-center text-sm leading-[1.72] text-muted-foreground">
          {needsDisplayName
            ? "choose a display name your friends will recognize."
            : "we've published a terms of service and privacy policy. please review and accept to continue."}
        </p>

        <form onSubmit={handleSubmit} noValidate className="mt-10 space-y-8">
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
              aria-describedby={error ? "onboarding-error" : undefined}
            />
          ) : null}

          {needsConsent ? (
            <div>
              <label className="flex cursor-pointer items-start gap-3">
                {/* The native box is drawn away (`appearance-none`) rather than
                    tinted with `accent-color`: the UA paints its own checkmark
                    white, and white on the amber fill is ~2.2:1 — below the 3:1
                    floor for a non-text graphic. Drawing it lets the mark be
                    `accent-foreground`, which is what the guide specifies on any
                    amber fill. Grid stacking (both children in cell 1/1) puts the
                    mark over the box without absolute positioning. */}
                <span className="mt-1 grid h-4 w-4 shrink-0 place-items-center">
                  <input
                    type="checkbox"
                    name="accept-terms"
                    checked={agreed}
                    onChange={(e) => setAgreed(e.target.checked)}
                    disabled={submitting}
                    // Checked is amber because "accent for selected" is the
                    // interactive-state half of amber's action category, not
                    // decoration. The ring carries a `floor` offset because an
                    // amber ring directly on the amber fill would be invisible.
                    // No disabled color change: the box is only ever disabled
                    // while a save is in flight, i.e. while it is checked, and
                    // Tailwind orders `disabled:` after `checked:` — a disabled
                    // recolor here would silently drop the amber mid-submit.
                    className="peer col-start-1 row-start-1 h-4 w-4 cursor-pointer appearance-none rounded-hair border border-muted-foreground bg-transparent transition-colors duration-150 checked:border-accent checked:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-floor disabled:cursor-not-allowed"
                  />
                  <CheckmarkIcon className="pointer-events-none col-start-1 row-start-1 hidden text-accent-foreground peer-checked:block" />
                </span>
                {/* The consent statement is the thing being agreed to, so it sits
                    at `foreground` rather than the `muted-foreground` used for
                    supporting copy. Both links are navigation, which is squarely
                    inside amber's action category — amber is a category rule, not
                    a per-screen count. */}
                <span className="text-sm leading-[1.72] text-foreground">
                  i agree to the{" "}
                  <Link
                    to="/terms"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-link underline underline-offset-[3px] hover:text-foreground"
                  >
                    terms of service
                  </Link>{" "}
                  and{" "}
                  <Link
                    to="/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-link underline underline-offset-[3px] hover:text-foreground"
                  >
                    privacy policy
                  </Link>
                </span>
              </label>
            </div>
          ) : null}

          {/* A failed save is a screen-level form error (ADR 0004) — the same
              category as ResetPasswordRoute's, so it takes the shared
              `destructive-text` + warning-icon treatment. Form errors are their
              own color category and consume nothing from this screen's amber. */}
          {error ? <FormError id="onboarding-error">{error}</FormError> : null}

          <Button type="submit" disabled={submitting || !canSubmit} className="w-full">
            {submitting ? "saving…" : "continue"}
          </Button>
        </form>
      </div>
    </main>
  );
}
