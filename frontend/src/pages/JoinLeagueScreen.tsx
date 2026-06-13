import type { InvitePreview } from "../services/api";
import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";

type JoinLeagueScreenProps = {
  preview: InvitePreview | null;
  loading: boolean;
  notFound: boolean;
  isAuthenticated: boolean;
  onJoin: () => void;
  joining: boolean;
  joinError?: string | null;
  onSignIn: () => void;
};

export function JoinLeagueScreen({
  preview,
  loading,
  notFound,
  isAuthenticated,
  onJoin,
  joining,
  joinError,
  onSignIn,
}: JoinLeagueScreenProps) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-8 sm:px-8">
      <div className="w-full max-w-sm text-center">
        {loading ? (
          <ConcentricRings size={88} spinning className="mx-auto" />
        ) : notFound ? (
          <>
            <ConcentricRings size={72} className="mx-auto" />
            <p className="mt-8 font-mono text-[13px] font-light text-muted">
              that invite link didn't work. ask for a new one.
            </p>
          </>
        ) : preview ? (
          <>
            {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
            <ConcentricRings size={72} accent className="mx-auto" />

            <h1 className="mt-8 font-serif text-[34px] leading-tight text-ink">
              {preview.league_name}
            </h1>
            <p className="mt-2 font-mono text-[13px] font-light text-muted">
              {preview.member_count} members
            </p>

            {isAuthenticated ? (
              <div className="mt-10 space-y-6">
                <Button type="button" onClick={onJoin} disabled={joining} className="w-full">
                  {joining ? "joining…" : "join league"}
                </Button>
                {joinError ? (
                  <p role="alert" className="font-mono text-[11px] text-ink">
                    {joinError}
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="mt-10 space-y-6">
                <p className="font-mono text-[13px] font-light text-muted">sign in to join</p>
                <Button type="button" onClick={onSignIn} className="w-full">
                  sign in
                </Button>
              </div>
            )}
          </>
        ) : null}
      </div>
    </main>
  );
}
