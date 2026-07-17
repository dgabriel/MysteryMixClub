import { ConcentricRings } from "../components/ConcentricRings";
import { TopNav } from "../components/TopNav";

const LINK_CLASS =
  "font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink";

/**
 * Public "about" page (MYS-155) — no auth required, reachable from the login
 * screen's footer and from TopNav's "about" link on every authed screen.
 * TopNav itself collapses to a login-only nav for signed-out visitors.
 */
export function AboutRoute() {
  return (
    <div className="min-h-screen flex flex-col">
      <TopNav />
      <main className="flex-1 flex flex-col items-center justify-center px-4 py-16 sm:px-8">
        <div className="w-full max-w-md">
          {/* Motif — the screen's single Rust use lives in the off-center ring dot. */}
          <ConcentricRings size={72} accent className="mx-auto" />

          <h1 className="mt-8 text-center font-serif text-[34px] leading-tight">about</h1>

          <p className="mt-6 font-mono text-[13px] font-light leading-relaxed text-ink">
            mysterymixclub is a place for close friends to trade songs, discover what everyone's
            been listening to, and put their taste on the line. no algorithm, no popularity
            contest, just people who love music, sharing it with people they love.
          </p>
          <p className="mt-4 font-mono text-[13px] font-light leading-relaxed text-ink">
            you can search and verify songs across spotify, apple music, youtube, and deezer.
            auto-generated playlists are more limited for now (spotify and youtube), with more
            platforms coming.
          </p>

          <div className="mt-10 border-t border-border pt-6">
            <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
              who built this
            </p>
            <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-ink">
              dawn gabriel, a software engineer who'd rather be making mixtapes. i design and
              build mysterymixclub end to end: the backend, the interface, the concentric rings
              on this page.
            </p>
            <a
              href="https://github.com/dgabriel"
              target="_blank"
              rel="noopener noreferrer"
              className={`mt-3 inline-block ${LINK_CLASS}`}
            >
              see my code on github
            </a>
            <p className="mt-4 font-mono text-[11px] font-light text-muted">
              built with{" "}
              <a
                href="https://claude.com/claude-code"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sage underline underline-offset-[3px] hover:text-ink"
              >
                claude code
              </a>{" "}
              and{" "}
              <a
                href="https://ollama.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sage underline underline-offset-[3px] hover:text-ink"
              >
                ollama
              </a>
              .
            </p>
          </div>

          <div className="mt-8 border-t border-border pt-6">
            <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
              support
            </p>
            <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-ink">
              if mysterymixclub made your group chat a little more musical, you can buy me a
              coffee.
            </p>
            <a
              href="https://www.venmo.com/u/dgbklyn"
              target="_blank"
              rel="noopener noreferrer"
              className={`mt-3 inline-block ${LINK_CLASS}`}
            >
              tip me on venmo
            </a>
          </div>

          <div className="mt-8 border-t border-border pt-6">
            <p className="font-mono text-[9px] uppercase tracking-[0.15em] text-muted">
              thanks
            </p>
            <p className="mt-3 font-mono text-[13px] font-light leading-relaxed text-ink">
              thanks to my old slam family pals, and my lovely family here in brooklyn.
            </p>
            <a
              href="https://youtu.be/kfV0WHgHQhI"
              target="_blank"
              rel="noopener noreferrer"
              className={`mt-3 inline-block ${LINK_CLASS}`}
            >
              thank you friends: big star
            </a>
          </div>

          <div className="mt-8 flex justify-center gap-4 border-t border-border pt-6">
            <a href="/terms" className={LINK_CLASS}>
              terms
            </a>
            <a href="/privacy" className={LINK_CLASS}>
              privacy
            </a>
          </div>
        </div>
      </main>
    </div>
  );
}
