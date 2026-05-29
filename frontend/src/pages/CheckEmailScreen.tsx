import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";

type CheckEmailScreenProps = {
  email: string;
  onBack?: () => void;
};

export function CheckEmailScreen({ email, onBack }: CheckEmailScreenProps) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 sm:px-8">
      <div className="w-full max-w-sm text-center">
        {/* Motif without the Rust dot — the one Rust use is the link below. */}
        <ConcentricRings size={72} className="mx-auto" />

        <h1 className="mt-8 font-serif text-[34px] leading-tight">check your email</h1>

        <p className="mt-4 font-mono text-[13px] font-light text-muted">
          we sent a sign-in link to
        </p>
        <p className="mt-1 font-mono text-[13px] text-ink break-all">{email}</p>
        <p className="mt-4 font-mono text-[13px] font-light text-muted">
          open it on this device to continue. the link expires soon.
        </p>

        {onBack ? (
          <div className="mt-10">
            <Button variant="link" type="button" onClick={onBack}>
              use a different email
            </Button>
          </div>
        ) : null}
      </div>
    </main>
  );
}
