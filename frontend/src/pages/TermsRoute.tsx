import { BrandLockup } from "../components/BrandLockup";
import { ContactEmail } from "../components/ContactEmail";
import { PaperSurface } from "../components/PaperSurface";
import { TopNav } from "../components/TopNav";

/**
 * Public Terms of Service page (MYS-183) — no auth required, linked from the
 * login screen footer, TopNav, and the onboarding/consent gate. Mirrors
 * AboutRoute's layout; TopNav collapses to a login-only nav for signed-out
 * visitors.
 */
export function TermsRoute() {
  return (
    <PaperSurface>
      <TopNav />
      <main className="flex-1 flex flex-col items-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Brand first, page second. The lockup's wordmark is a `p`, not a
              heading — `terms of service` below stays this page's one `h1`, so
              the heading outline still describes the document rather than the
              site. Visual weight and heading semantics are independent; the
              wordmark is the loudest thing here without being a heading. */}
          <BrandLockup />

          <h1 className="mt-10 border-t border-ink-hairline pt-8 text-center font-display text-[2rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
            terms of service
          </h1>
          <p className="mt-2 text-center text-sm leading-[1.72] text-ink-muted">
            last updated july 2026
          </p>

          <div className="mt-10 space-y-8 text-sm leading-[1.72] text-ink">
            <section>
              <p>
                mysterymixclub ("we," "us," "the app") is an invite-only music club for close-knit
                friend groups. by creating an account, you agree to these terms.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                the basics
              </h2>
              <p className="mt-3">
                mysterymixclub is currently in beta. features, availability, and these terms may
                change as the product develops. we'll do our best to give you notice of material
                changes.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                your account
              </h2>
              <p className="mt-3">
                access is invite-only. you're responsible for the songs, notes, and display name you
                submit, and for keeping your sign-in email under your control. don't submit content
                you don't have the right to share, and don't use the app to harass or impersonate
                other members.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                third-party services
              </h2>
              <p className="mt-3">
                submitting and resolving songs relies on third-party streaming platforms (spotify,
                youtube, deezer, apple music) and song-matching services. we don't control their
                availability, and a platform's own terms govern your use of it.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                account deletion
              </h2>
              <p className="mt-3">
                you can delete your account at any time from your profile. this removes your
                personal data — see the{" "}
                <a
                  href="/privacy"
                  className="text-ink-link underline underline-offset-[3px] hover:text-ink"
                >
                  privacy policy
                </a>{" "}
                for what that covers.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                as-is, beta software
              </h2>
              <p className="mt-3">
                mysterymixclub is provided "as is," without warranties of any kind, during this beta
                period. we're not liable for lost data, service interruptions, or issues arising
                from third-party platforms this app depends on.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                governing law
              </h2>
              <p className="mt-3">
                these terms are governed by the laws of the State of New York, without regard to
                conflict-of-law principles.
              </p>
            </section>

            <section className="border-t border-ink-hairline pt-6">
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                questions
              </h2>
              <p className="mt-3">
                <ContactEmail
                  user="privacy"
                  domain="mysterymixclub.com"
                  label="email us"
                  className="text-ink-link underline underline-offset-[3px] hover:text-ink"
                />{" "}
                with any questions about these terms.
              </p>
            </section>
          </div>
        </div>
      </main>
    </PaperSurface>
  );
}
