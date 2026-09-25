import { ConcentricRings } from "./ConcentricRings";
import { PaperSurface } from "./PaperSurface";
import { useConnectivityPhase, useHasInlineOfflineHost } from "../lib/offline";

/**
 * The "no internet connection" state (MysteryMixClub-ga4y). Dawn's call:
 * a full-screen state that replaces the page (the nav stays on authed
 * screens), a brief "back online" on reconnect, then the page reloads its
 * data unless the member has typed something they haven't saved. The page
 * stays mounted underneath while this shows (AuthedLayout only hides it), so
 * going offline never loses anything typed.
 */
export function OfflineScreen({ reconnected }: { reconnected: boolean }) {
  return (
    <PaperSurface nested>
      <main className="flex flex-1 flex-col items-center justify-center px-4 py-16 text-center sm:px-8">
        <div role="status" aria-live="polite" className="flex flex-col items-center">
          <ConcentricRings size={88} spinning={!reconnected} onPaper className="mx-auto" />
          <h1 className="mt-8 font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug text-ink">
            {reconnected ? "back online" : "you're offline"}
          </h1>
          <p className="mt-3 max-w-xs text-sm leading-[1.72] text-ink-muted">
            {reconnected
              ? "picking up where you left off."
              : "we'll pick up where you left off when you're back."}
          </p>
        </div>
      </main>
    </PaperSurface>
  );
}

/**
 * The offline state for everything outside AuthedLayout: sign-in, the public
 * pages, and the startup session restore (which waits for the connection
 * instead of showing the sign-in form). Rendered once, above the router.
 */
export function AppOfflineOverlay() {
  const phase = useConnectivityPhase();
  const hosted = useHasInlineOfflineHost();
  if (phase === "online" || hosted) return null;
  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-paper">
      <OfflineScreen reconnected={phase === "reconnected"} />
    </div>
  );
}
