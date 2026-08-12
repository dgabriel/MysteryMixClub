import type { InvitePreview } from "../services/api";
import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";
import { FormError } from "../components/FormError";
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
            /* Resolving the invite. The disc spins, neutral: a spinner is not an
               identity placement, so the amber centre label is reserved for the
               preview hero below — which can never render at the same time. */
            <ConcentricRings size={88} spinning className="mx-auto" />
          ) : expired ? (
            <>
              {/* Neutral. This is a dead end, not the screen's arrival state, so
                  it does not claim the one hero mark ADR 0010 allows here. */}
              <ConcentricRings size={72} className="mx-auto" />
              {/* An expired link is a statement of fact about the link, not a
                  validation error about something the user typed, so it stays on
                  the foreground ramp rather than taking `destructive-text`
                  (ADR 0004) — the same call VerifyScreen makes. `foreground`
                  rather than `muted-foreground` because with no heading above it
                  this paragraph IS the screen's primary text. */}
              <p className="mt-8 text-sm leading-[1.72] text-foreground">
                this link has expired. ask the organizer for a new one.
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
              {/* Neutral, same reasoning as the expired state. */}
              <ConcentricRings size={72} className="mx-auto" />
              {/* Plain `foreground` for the same ADR 0004 reason as above. */}
              <p className="mt-8 text-sm leading-[1.72] text-foreground">
                that invite link didn't work. ask for a new one.
              </p>
            </>
          ) : preview ? (
            <>
              {/* The brand mark, accented — the screen's one amber hero mark.
                  ADR 0010 bounds amber-as-identity to the shared nav's
                  persistent 28px mark (rendered above for authenticated
                  visitors only) plus at most one hero mark in a screen's own
                  content, and JoinClubScreen is named there. The four discs in
                  this screen are mutually exclusive branches, so only ever one
                  renders, and this is the branch that earns it: a resolved
                  invite is the screen's arrival state. */}
              <ConcentricRings size={72} accent className="mx-auto" />

              {preview.club_id !== null ? (
                <>
                  <h1 className="mt-8 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
                    {preview.club_name}
                  </h1>
                  {/* Mono at normal tracking is the system's signature for a
                      value, which is what a member count is. */}
                  <p className="mt-2 font-mono text-meta text-muted-foreground">
                    {preview.member_count} members
                  </p>
                </>
              ) : (
                // Platform invite (MYS-182): a signup grant, not a specific
                // club — no name/member count to show. An authenticated
                // visitor never reaches this screen (the route sends them home
                // instead), so only the signed-out copy below applies in practice.
                <h1 className="mt-8 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
                  you're invited to mysterymixclub
                </h1>
              )}

              {isAuthenticated && preview.club_id !== null ? (
                <div className="mt-10 space-y-6">
                  <Button type="button" onClick={onJoin} disabled={joining} className="w-full">
                    {joining ? "joining…" : "join club"}
                  </Button>
                  {/* A rejected join — a full club, a revoked invite, a server
                      error — is a claim about the user's own submitted attempt,
                      which is the ADR 0004 form-error category rather than a
                      third party's outcome. It takes the shared
                      `destructive-text` + warning-icon treatment, and form
                      errors consume nothing from this screen's amber. */}
                  {joinError ? <FormError>{joinError}</FormError> : null}
                </div>
              ) : !isAuthenticated ? (
                <div className="mt-10 space-y-6">
                  {/* Supporting copy above the CTA, so `muted-foreground`. */}
                  <p className="text-sm leading-[1.72] text-muted-foreground">
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
