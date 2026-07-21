import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { ContactEmail } from "../components/ContactEmail";
import { ConcentricRings } from "../components/ConcentricRings";
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
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm text-center">
        {/* Motif without the Rust dot — when the fallback below shows, its
            "use a different email" link is the one Rust use on this screen;
            the waitlist form has none. */}
        <ConcentricRings size={72} className="mx-auto" />

        <h1 className="mt-8 font-serif text-[34px] leading-tight">check your email</h1>

        <p className="mt-4 font-mono text-[13px] font-light text-muted">
          if you have an account, we sent a sign-in link to
        </p>
        <p className="mt-1 font-mono text-[13px] text-ink break-all">{email}</p>
        <p className="mt-4 font-mono text-[13px] font-light text-muted">
          open it on this device to continue. the link expires soon.
        </p>

        {waitlistEnabled === undefined ? null : waitlistEnabled ? (
          <>
            {/* Same-response-either-way sign-in (MYS-127/182) means someone
                without an account sees this exact screen and would otherwise
                wait for an email that's never coming — say so plainly, and
                give them the real next step instead of a dead end. */}
            <p className="mt-6 font-mono text-[11px] font-light text-muted">
              no account yet? you won&apos;t receive anything here — join the waitlist below.
            </p>
            <WaitlistForm />
          </>
        ) : (
          <>
            <p className="mt-6 font-mono text-[11px] font-light text-muted">
              no account yet? you won&apos;t receive anything — you&apos;ll need an invite.{" "}
              <ContactEmail
                user="info"
                domain="mysterymixclub.com"
                label="email us"
                className="text-ink underline underline-offset-[3px]"
              />{" "}
              to request one.
            </p>
            {onBack ? (
              <div className="mt-10">
                <Button variant="link" type="button" onClick={onBack}>
                  use a different email
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </main>
  );
}
