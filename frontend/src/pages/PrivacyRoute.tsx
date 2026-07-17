import { ConcentricRings } from "../components/ConcentricRings";
import { ContactEmail } from "../components/ContactEmail";
import { TopNav } from "../components/TopNav";

/**
 * Public Privacy Policy page (MYS-183) — no auth required, linked from the
 * login screen footer, TopNav, and the onboarding/consent gate. Content
 * mirrors the real data practices in docs/technical/technical-design.md §10;
 * keep the two in sync if either changes.
 */
export function PrivacyRoute() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopNav />
      <main className="flex-1 flex flex-col items-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
          <ConcentricRings size={72} accent className="mx-auto" />

          <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">
            privacy policy
          </h1>
          <p className="mt-2 text-center font-mono text-[11px] font-light text-muted">
            last updated july 2026
          </p>

          <p className="mt-8 font-mono text-[13px] font-semibold leading-relaxed text-ink">
            while ai was used to help write the code, there are no ai features in this app and no
            ai will ingest your data.
          </p>

          <div className="mt-8 space-y-8 font-mono text-[13px] font-light leading-relaxed text-ink">
            <section>
              <p>
                this page explains what mysterymixclub collects, why, and what control you have
                over it.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                what we collect
              </p>
              <p className="mt-3">
                your email, display name, and preferred streaming service; the songs, notes, and
                votes you submit to leagues you're a member of; and basic session data needed to
                keep you signed in.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                what we don't do
              </p>
              <p className="mt-3">
                no individual behavior tracking and no third-party analytics scripts (no google
                analytics, no mixpanel). we only look at aggregate, app-wide numbers — total
                leagues, total rounds, total submissions — never a single user's activity pattern.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                cookies
              </p>
              <p className="mt-3">
                the only cookie we set is a strictly-necessary, HttpOnly session cookie that keeps
                you signed in. it isn't used for tracking or advertising, and it's not readable by
                any script running in your browser.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                who we share it with
              </p>
              <p className="mt-3">
                we use a small number of third-party services to run the app: resend (sending
                sign-in emails), spotify / youtube / deezer / apple music (resolving and playing
                the songs you submit), and digitalocean (hosting our servers and database). each
                only receives what it needs to do its job — we don't sell or share your data for
                advertising.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                your data, your control
              </p>
              <p className="mt-3">
                download a copy of everything tied to your account — profile, submissions, votes,
                and notes — any time from your profile page. delete your account any time from the
                same page: this cascades to your submissions, votes, notes, sessions, and league
                memberships, with a scheduled hard purge of any remaining trace within 30 days.
              </p>
            </section>

            <section>
              <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
                changes to this policy
              </p>
              <p className="mt-3">
                if we make a material change to how we handle your data, we'll update this page
                and ask returning members to review it again.
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
                with any privacy questions or requests.
              </p>
            </section>
          </div>
        </div>
      </main>
    </div>
  );
}
