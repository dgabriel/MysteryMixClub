import { ConcentricRings } from "../components/ConcentricRings";
import { TopNav } from "../components/TopNav";

const LINK_CLASS =
  "font-mono uppercase tracking-mono text-label text-accent underline underline-offset-[3px] transition-colors duration-150 hover:text-foreground";

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
          {/* The brand mark. Its amber is the identity category (ADR 0010), not a
              decorative accent: this page's one hero mark, alongside the nav's
              persistent mark, is exactly the two-placement bound. */}
          <ConcentricRings size={72} accent className="mx-auto" />

          <h1 className="mt-8 text-center font-display text-[2rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">about</h1>

          <p className="mt-6 text-sm leading-[1.72] text-foreground">
            mysterymixclub is a place for friends to trade songs, discover what everyone's
            been listening to, and put their taste on the line. no algorithm, no popularity
            contest, just people who love music, sharing it with people they love.
          </p>
          <p className="mt-4 text-sm leading-[1.72] text-foreground">
            you can search and verify songs across spotify, apple music, deezer, youtube, youtube
            music, and bandcamp. we auto-generate playlists for spotify, apple music, and youtube; a
            track that lives only on bandcamp comes through as a link everyone can open, rather than
            on those playlists.
          </p>

          <div className="mt-10 border-t border-hairline pt-6">
            <p className="font-mono text-mini uppercase tracking-mono-wide text-muted-foreground">
              who built this
            </p>
            <p className="mt-3 text-sm leading-[1.72] text-foreground">
              dawn gabriel, a software engineer who loves art and poems and rock and roll. i design and
              build mysterymixclub end to end: the backend, the interface, the concentric rings
              on this page.  please reach out if you have questions, feedback, or want to contribute! 
              d gabriel at gmail dot com.
            </p>
            <a
              href="https://github.com/dgabriel"
              target="_blank"
              rel="noopener noreferrer"
              className={`mt-3 inline-block ${LINK_CLASS}`}
            >
              see the code on github
            </a>
            <p className="mt-4 text-sm leading-[1.72] text-muted-foreground">
              built with{" "}
              <a
                href="https://claude.com/claude-code"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent underline underline-offset-[3px] hover:text-foreground"
              >
                claude code
              </a>{" "}
              and{" "}
              <a
                href="https://ollama.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent underline underline-offset-[3px] hover:text-foreground"
              >
                ollama
              </a>
              .
            </p>
          </div>

          <div className="mt-8 border-t border-hairline pt-6">
            <p className="font-mono text-mini uppercase tracking-mono-wide text-muted-foreground">
              support
            </p>
            <p className="mt-3 text-sm leading-[1.72] text-foreground">
              i will never *make* you look at an ad.  i won't use ai to scrape your data and sell it.
              for many people, the app is free, but it does cost me a lil money to run.  the
              total cost for developing this app was about $220 including hosting on digital ocean,
               domain registration, apple developer program, apple music, and extra claude usage tokens.
               monthly ongoing cost is just hosting and claude tokens, which is about $30-$40.  annual costs
               include apple developer program and domain renewal, which is about $120.  
               if you want to help me keep this app running, or if you just want to say thanks,
              you can tip me on venmo.  any amount is appreciated{" "}
              {/* Deliberate: Dawn added this as a second decorative accent under the
                  retired system, and the style guide carries it forward by name. It is
                  the one sanctioned exception to amber being action, achievement, or
                  identity only. Do not remove it and do not flag it as a violation. */}
              <span className="text-accent">&lt;3</span>
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

          <div className="mt-8 border-t border-hairline pt-6">
            <p className="font-mono text-mini uppercase tracking-mono-wide text-muted-foreground">
              thanks
            </p>
            <p className="mt-3 text-sm leading-[1.72] text-foreground">
              thanks to my dear slam family pals, nv pals, and my lovely family here in brooklyn.
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

          <div className="mt-8 flex justify-center gap-4 border-t border-hairline pt-6">
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
