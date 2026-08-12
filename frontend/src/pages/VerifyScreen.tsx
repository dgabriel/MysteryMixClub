import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";

type VerifyScreenProps = {
  state: "verifying" | "error";
  onBackToLogin?: () => void;
  /** Optional override for the error heading (defaults to the link-failed copy). */
  heading?: string;
  /** Optional override for the error body — used for invite-required / at-capacity
   *  / expired-link cases so each reads in its own calm words. */
  message?: string;
};

export function VerifyScreen({ state, onBackToLogin, heading, message }: VerifyScreenProps) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm text-center">
        {state === "verifying" ? (
          <>
            {/* Loading is the slowly rotating motif — not a spinner. The disc is
                unaccented: amber-as-identity is bounded to the shared nav's mark
                plus at most one hero mark per screen, and this screen is not one
                of the ones that carries the hero mark (ADR 0010). 88px is the
                page-hero size, and the disc is the only thing on screen here. */}
            <ConcentricRings size={88} spinning className="mx-auto" />
            {/* Mono eyebrow. `text-mini` rather than a 9px arbitrary value —
                this label carries the only information on the screen, so it sits
                at the readable floor, not below it. */}
            <p className="mt-8 font-mono uppercase tracking-mono-wide text-mini text-muted-foreground">
              verifying
            </p>
          </>
        ) : (
          <>
            {/* Unaccented for the same ADR 0010 reason as above. */}
            <ConcentricRings size={72} className="mx-auto" />
            <h1 className="mt-8 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
              {heading ?? "that link didn’t work"}
            </h1>
            {/* A failed or expired link is a statement of fact about the link,
                not a form validation error, so it stays on the foreground ramp
                rather than taking `destructive-text` (ADR 0004). */}
            <p className="mt-4 text-sm leading-[1.72] text-muted-foreground">
              {message ?? "it may have expired or already been used."}
            </p>

            {onBackToLogin ? (
              <div className="mt-10">
                {/* Amber, because a text button is still an action. */}
                <Button variant="link" type="button" onClick={onBackToLogin}>
                  request a new one
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </main>
  );
}
