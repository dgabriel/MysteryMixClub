import type { InvitePreview } from "../services/api";
import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";
import { TopNav } from "../components/TopNav";

type JoinClubScreenProps = {
  preview: InvitePreview | null;
  loading: boolean;
  notFound: boolean;
  /** The invite link has expired (410) — distinct calm copy from notFound. */
  expired?: boolean;
  isAuthenticated: boolean;
  onJoin: () => void;
  joining: boolean;
  joinError?: string | null;
  onSignIn: () => void;
  /** Expired-link CTAs (MYS-181): distinct from onSignIn — the link is dead
   *  either way, so there's nothing to return to afterward. */
  onExpiredLogin: () => void;
  onExpiredGoHome: () => void;
};

export function JoinClubScreen({
  preview,
  loading,
  notFound,
  expired,
  isAuthenticated,
  onJoin,
  joining,
  joinError,
  onSignIn,
  onExpiredLogin,
  onExpiredGoHome,
}: JoinClubScreenProps) {
  return (
    <div className="flex min-h-screen flex-col">
      {/* Authenticated visitors get the shared nav (MYS-136). Logged-out
          previewers have no session to drive it, so it stays absent for them. */}
      {isAuthenticated ? <TopNav /> : null}
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-16 sm:px-8">
      <div className="w-full max-w-sm text-center">
        {loading ? (
          <ConcentricRings size={88} spinning className="mx-auto" />
        ) : expired ? (
          <>
            <ConcentricRings size={72} className="mx-auto" />
            <p className="mt-8 font-mono text-[13px] font-light text-muted">
              this link has expired — ask the organizer for a new one.
            </p>
            <div className="mt-8">
              {isAuthenticated ? (
                <Button type="button" onClick={onExpiredGoHome} className="w-full">
                  go home
                </Button>
              ) : (
                <Button type="button" onClick={onExpiredLogin} className="w-full">
                  sign in
                </Button>
              )}
            </div>
          </>
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

            {preview.club_id !== null ? (
              <>
                <h1 className="mt-8 font-serif text-[34px] leading-tight text-ink">
                  {preview.club_name}
                </h1>
                <p className="mt-2 font-mono text-[13px] font-light text-muted">
                  {preview.member_count} members
                </p>
              </>
            ) : (
              // Platform invite (MYS-182): a signup grant, not a specific
              // club — no name/member count to show. An authenticated
              // visitor never reaches this screen (the route sends them home
              // instead), so only the signed-out copy below applies in practice.
              <h1 className="mt-8 font-serif text-[34px] leading-tight text-ink">
                you're invited to mysterymixclub
              </h1>
            )}

            {isAuthenticated && preview.club_id !== null ? (
              <div className="mt-10 space-y-6">
                <Button type="button" onClick={onJoin} disabled={joining} className="w-full">
                  {joining ? "joining…" : "join club"}
                </Button>
                {joinError ? (
                  <p role="alert" className="font-mono text-[11px] text-ink">
                    {joinError}
                  </p>
                ) : null}
              </div>
            ) : !isAuthenticated ? (
              <div className="mt-10 space-y-6">
                <p className="font-mono text-[13px] font-light text-muted">
                  {preview.club_id !== null ? "sign in to join" : "sign in to get started"}
                </p>
                <Button type="button" onClick={onSignIn} className="w-full">
                  sign in
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </main>
    </div>
  );
}
