import { ConcentricRings } from "../components/ConcentricRings";
import { ContactEmail } from "../components/ContactEmail";
import { TopNav } from "../components/TopNav";

/**
 * Public Terms of Service page (MYS-183) — no auth required, linked from the
 * login screen footer, TopNav, and the onboarding/consent gate. Mirrors
 * AboutRoute's layout; TopNav collapses to a login-only nav for signed-out
 * visitors.
 */
export function TermsRoute() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopNav />
      <main className="flex-1 flex flex-col items-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
          <ConcentricRings size={72} accent className="mx-auto" />

          <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">
            terms of service
          </h1>
          <p className="mt-2 text-center font-mono text-[11px] font-light text-muted">
            last updated july 2026
          </p>

          <div className="mt-10 space-y-8 font-mono text-[13px] font-light leading-relaxed text-ink">
            <section>
              <p>
                mysterymixclub ("we," "us," "the app") is an invite-only music club for
                close-knit friend groups. by creating an account, you agree to these terms.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                the basics
              </p>
              <p className="mt-3">
                mysterymixclub is currently in beta. features, availability, and these terms may
                change as the product develops. we'll do our best to give you notice of material
                changes.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                your account
              </p>
              <p className="mt-3">
                access is invite-only. you're responsible for the songs, notes, and display name
                you submit, and for keeping your sign-in email under your control. don't submit
                content you don't have the right to share, and don't use the app to harass or
                impersonate other members.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                third-party services
              </p>
              <p className="mt-3">
                submitting and resolving songs relies on third-party streaming platforms (spotify,
                youtube, deezer, apple music) and song-matching services. we don't control their
                availability, and a platform's own terms govern your use of it.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                account deletion
              </p>
              <p className="mt-3">
                you can delete your account at any time from your profile. this removes your
                personal data — see the{" "}
                <a
                  href="/privacy"
                  className="text-sage underline underline-offset-[3px] hover:text-ink"
                >
                  privacy policy
                </a>{" "}
                for what that covers.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                as-is, beta software
              </p>
              <p className="mt-3">
                mysterymixclub is provided "as is," without warranties of any kind, during this
                beta period. we're not liable for lost data, service interruptions, or issues
                arising from third-party platforms this app depends on.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                governing law
              </p>
              <p className="mt-3">
                these terms are governed by the laws of the State of New York, without regard to
                conflict-of-law principles.
              </p>
            </section>

            <section className="border-t border-border pt-6">
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                questions
              </p>
              <p className="mt-3">
                <ContactEmail
                  user="privacy"
                  domain="mysterymixclub.com"
                  label="email us"
                  className="text-sage underline underline-offset-[3px] hover:text-ink"
                />{" "}
                with any questions about these terms.
              </p>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
