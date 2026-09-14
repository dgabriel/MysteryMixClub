import { useId, useRef, type ReactNode } from "react";
import { Button } from "./Button";
import { CheckmarkIcon } from "./CheckmarkIcon";
import { useFocusTrap } from "../hooks/useFocusTrap";

/** Small line "×" glyph, matching ReleaseNotesModal's own local close icon --
 *  there's still no shared CloseIcon primitive to reuse (see that file). */
function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M3 3l10 10M13 3 3 13" />
    </svg>
  );
}

export type OnboardingGuideStep = {
  title: string;
  description: string;
  /** Renders a checkmark instead of the step's ordinal -- used only by the
   *  invite-welcome guide's first step, which is already true by the time
   *  the guide can show (you can't see it without having joined). */
  complete?: boolean;
};

type OnboardingGuideModalProps = {
  eyebrow: string;
  heading: ReactNode;
  intro: ReactNode;
  steps: OnboardingGuideStep[];
  primaryLabel: string;
  onPrimary: () => void;
  onDismiss: () => void;
};

/**
 * Shared chrome for the two "how it works" onboarding guides
 * (MysteryMixClub-6eo8): the empty-clubs welcome (first landing, no clubs
 * yet) and the club-invite welcome (just joined a club via invite). Adapted
 * from the approved mockups (docs/output/invite-preview/*.html) -- same
 * content, layout and behavior, restyled onto this app's tokens and its one
 * existing modal precedent (ReleaseNotesModal): a `sheet` (Z4) panel with
 * `shadow-z4` and no border.
 *
 * Adds focus trapping, Escape-to-dismiss, and focus restoration on close
 * (via `useFocusTrap`) -- behavior neither ReleaseNotesModal nor any other
 * modal in the app has needed before now, since this is the first modal a
 * guide can plausibly leave open for a while (there's reading to do) rather
 * than dismiss in the same glance it opens in.
 */
export function OnboardingGuideModal({
  eyebrow,
  heading,
  intro,
  steps,
  primaryLabel,
  onPrimary,
  onDismiss,
}: OnboardingGuideModalProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, onDismiss);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-floor/80 px-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-tile bg-sheet p-6 shadow-z4"
      >
        <div className="flex items-center justify-between gap-4">
          <span className="font-mono text-mini uppercase tracking-mono-caps text-muted-foreground">
            {eyebrow}
          </span>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="dismiss welcome guide"
            className="text-foreground transition-colors duration-150 hover:text-accent"
          >
            <CloseIcon />
          </button>
        </div>

        <h2
          id={titleId}
          className="mt-5 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug text-foreground"
        >
          {heading}
        </h2>
        <p className="mt-3 text-sm leading-[1.6] text-muted-foreground">{intro}</p>

        <ol className="mt-6 space-y-5">
          {steps.map((step, i) => (
            <li key={step.title} className="flex gap-3.5">
              <span
                className={[
                  "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border font-mono text-mini",
                  step.complete
                    ? "border-positive text-positive"
                    : "border-hairline-strong text-muted-foreground",
                ].join(" ")}
              >
                {step.complete ? (
                  <>
                    <CheckmarkIcon />
                    <span className="sr-only">complete</span>
                  </>
                ) : (
                  i + 1
                )}
              </span>
              <div>
                <h3 className="font-display text-base font-bold uppercase leading-none text-foreground">
                  {step.title}
                </h3>
                <p className="mt-1.5 text-sm leading-[1.55] text-muted-foreground">
                  {step.description}
                </p>
              </div>
            </li>
          ))}
        </ol>

        <Button type="button" onClick={onPrimary} className="mt-2 w-full">
          {primaryLabel}
        </Button>
        <p className="mt-4 text-center text-mini leading-[1.5] text-muted-foreground">
          find this guide again under &ldquo;how it works.&rdquo;
        </p>
      </div>
    </div>
  );
}
