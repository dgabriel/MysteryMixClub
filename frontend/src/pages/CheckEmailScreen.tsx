import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ContactEmail } from "../components/ContactEmail";
import { ConcentricRings } from "../components/ConcentricRings";
import { PaperSurface } from "../components/PaperSurface";
import { WaitlistForm } from "../components/WaitlistForm";
import { getWaitlistEnabled } from "../services/api";

type CheckEmailScreenProps = {
  email: string;
  onBack?: () => void;
};

export function CheckEmailScreen({ email, onBack }: CheckEmailScreenProps) {
  // Same fail-safe pattern as EmailEntryScreen (MYS-215): undefined while
  // checking, falls back to "email us" on disabled/error. When enabled, the
  // actual join form renders here (not just a pointer back to /login) —
  // replacing "use a different email", since anyone without an account
  // needs the waitlist, not a retry.
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

  return (
    <PaperSurface>
      <main className="flex flex-1 flex-col items-center justify-center px-4 sm:px-8">
        <div className="w-full max-w-sm text-center">
          {/* The disc, unaccented. Amber-as-identity is bounded to the shared
            nav's mark plus at most one hero mark per screen, and this screen is
            not one of the ones that carries the hero mark (ADR 0010). */}
          <ConcentricRings size={72} onPaper className="mx-auto" />

          <h1 className="mt-8 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
            check your email
          </h1>

          <p className="mt-4 text-sm leading-[1.72] text-ink-muted">
            if you have an account, we sent a sign-in link to
          </p>
          {/* The address is a value, so it takes mono at normal tracking. */}
          <p className="mt-1 font-mono text-sm text-ink break-all">{email}</p>
          <p className="mt-4 text-sm leading-[1.72] text-ink-muted">
            open it on this device to continue. the link expires soon.
          </p>

          {waitlistEnabled === undefined ? null : waitlistEnabled ? (
            <WaitlistForm />
          ) : (
            <>
              <p className="mt-6 text-sm leading-[1.72] text-ink-muted">
                no account yet? you won&apos;t receive anything — you&apos;ll need an invite.{" "}
                <ContactEmail
                  user="info"
                  domain="mysterymixclub.com"
                  label="email us"
                  className="text-ink-link underline underline-offset-[3px] hover:text-ink"
                />{" "}
                to request one.
              </p>
              {onBack ? (
                <div className="mt-10">
                  <Button variant="link" onPaper type="button" onClick={onBack}>
                    use a different email
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </div>
      </main>
    </PaperSurface>
  );
}
