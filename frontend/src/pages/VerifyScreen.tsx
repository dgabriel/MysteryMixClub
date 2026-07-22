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
            {/* Loading is the slowly rotating motif — not a spinner. No Rust. */}
            <ConcentricRings size={88} spinning className="mx-auto" />
            <p className="mt-8 font-mono uppercase tracking-label text-[9px] text-muted">
              verifying
            </p>
          </>
        ) : (
          <>
            <ConcentricRings size={72} className="mx-auto" />
            <h1 className="mt-8 font-serif text-[28px] leading-tight">
              {heading ?? "that link didn’t work"}
            </h1>
            <p className="mt-4 font-mono text-[13px] font-light text-muted">
              {message ?? "it may have expired or already been used."}
            </p>

            {onBackToLogin ? (
              <div className="mt-10">
                {/* The screen's one Rust use — the recovery action. */}
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
