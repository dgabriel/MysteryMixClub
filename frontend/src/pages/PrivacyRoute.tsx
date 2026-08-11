import { BrandLockup } from "../components/BrandLockup";
import { ContactEmail } from "../components/ContactEmail";
import { PaperSurface } from "../components/PaperSurface";
import { TopNav } from "../components/TopNav";

/**
 * Public Privacy Policy page (MYS-183) — no auth required, linked from the
 * login screen footer, TopNav, and the onboarding/consent gate. Content
 * mirrors the real data practices in docs/technical/technical-design.md §10;
 * keep the two in sync if either changes.
 */
export function PrivacyRoute() {
  return (
    <PaperSurface>
      <TopNav />
      <main className="flex-1 flex flex-col items-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Brand first, page second. The lockup's wordmark is a `p`, not a
              heading — `privacy policy` below stays this page's one `h1`, so the
              heading outline still describes the document rather than the site.
              Visual weight and heading semantics are independent; the wordmark
              is the loudest thing here without being a heading. */}
          <BrandLockup />

          <h1 className="mt-10 border-t border-ink-hairline pt-8 text-center font-display text-[2rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
            privacy policy
          </h1>
          <p className="mt-2 text-center font-mono text-meta text-ink-muted">
            last updated july 2026
          </p>

          <p className="mt-8 text-sm font-medium leading-[1.72] text-ink">
            while ai was used to help write the code, there are no ai features in this app and no ai
            will ingest your data.
          </p>

          <div className="mt-8 space-y-8 text-sm leading-[1.72] text-ink">
            <section>
              <p>
                this page explains what mysterymixclub collects, why, and what control you have over
                it.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                what we collect
              </h2>
              <p className="mt-3">
                your email, display name, and preferred streaming service; the songs, notes, and
                votes you submit to clubs you're a member of; and basic session data needed to keep
                you signed in.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                what we don't do
              </h2>
              <p className="mt-3">
                no individual behavior tracking and no third-party analytics scripts (no google
                analytics, no mixpanel). we only look at aggregate, app-wide numbers — total clubs,
                total mystery mixes, total submissions — never a single user's activity pattern.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                cookies
              </h2>
              <p className="mt-3">
                the only cookie we set is a strictly-necessary, HttpOnly session cookie that keeps
                you signed in. it isn't used for tracking or advertising, and it's not readable by
                any script running in your browser.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                subprocessors
              </h2>
              <p className="mt-3">
                two services process personal data on our behalf, each under its own data processing
                agreement: resend (your email address, to deliver sign-in links and notifications)
                and digitalocean (hosting our servers and database, so everything you store in the
                app).
              </p>
              <p className="mt-3">
                spotify, youtube, apple music, and deezer help us look up and play the songs you
                submit. they only ever receive a song title, artist, and isrc to search for or play
                back a track, never your email, name, or any other personal data, so they aren't
                subprocessors of your personal data. we don't sell or share your data for
                advertising with anyone.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                your data, your control
              </h2>
              <p className="mt-3">
                download a copy of everything tied to your account (profile, submissions, votes, and
                notes) any time from your profile page, satisfying your right of access and data
                portability under gdpr articles 15 and 20. delete your account any time from the
                same page: this cascades to your submissions, votes, notes, sessions, and club
                memberships, with a scheduled hard purge of any remaining trace within 30 days.
              </p>
            </section>

            <section>
              <h2 className="font-mono text-mini uppercase tracking-mono-wide text-ink-accent">
                changes to this policy
              </h2>
              <p className="mt-3">
                if we make a material change to how we handle your data, we'll update this page and
                ask returning members to review it again.
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
                with any privacy questions or requests.
              </p>
            </section>
          </div>
        </div>
      </main>
    </PaperSurface>
  );
}
