/**
 * The one modal look (ADR 0038, MysteryMixClub-3fjt): a white `paper` panel
 * with a clear 2px `ink` border over the dark scrim. Everything inside uses
 * the paper ramp (`ink`, `ink-muted`, `ink-accent`, `ink-destructive`) and
 * the `onPaper` component variants; the dark ramp is invisible on white.
 *
 * Replaces the dark `sheet` panel, whose body copy in `muted-foreground`
 * measured 3.49:1 and failed AA. Shared so every modal stays identical.
 * `TopNav`'s mobile menu is chrome, not a modal, and keeps its dark `sheet`.
 */
export const MODAL_SCRIM = "fixed inset-0 z-50 flex items-center justify-center bg-floor/80 px-4";

export const MODAL_PANEL = "rounded-tile border-2 border-ink bg-paper text-ink shadow-art-ink";

/** The dismiss (×) control in a modal's header. */
export const MODAL_CLOSE =
  "text-ink transition-colors duration-150 hover:text-ink-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink-accent";
