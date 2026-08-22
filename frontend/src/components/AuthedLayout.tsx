import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation, useOutletContext } from "react-router";
import { TopNav } from "./TopNav";

/** A contextual back target for the shared nav (e.g. mix → its club). */
type NavBack = { label: string; to: string };

type AuthedOutletContext = {
  /** Set (or clear with null) the nav's contextual back affordance. Screens that
   *  need it — currently only the mix screen — call this once they know the
   *  target; everyone else leaves it null and no back link shows. */
  setNavBack: (back: NavBack | null) => void;
};

/**
 * Layout for every authenticated screen: renders the shared TopNav once, above
 * the routed content. Mounting the nav here (rather than per screen) guarantees
 * it appears on all authed routes and never on the pre-auth ones (login / verify
 * / onboarding / invite), which live outside this layout.
 *
 * The only per-route nav variation is the contextual "← club" link on the
 * mix screen. Since a layout can't read a child route's loaded data, the child
 * pushes its back target up through the outlet context (useNavBack).
 */
export function AuthedLayout() {
  const [navBack, setNavBack] = useState<NavBack | null>(null);
  const setNavBackCb = useCallback((back: NavBack | null) => setNavBack(back), []);
  const contentRef = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

  // Move focus to the new page's content on every client-side navigation, so
  // keyboard/AT users get a cue that the "page" changed instead of focus
  // silently staying on whatever nav link was just activated.
  //
  // `preventScroll` is load-bearing. This container starts just below the nav
  // and is as tall as the page, so a plain focus() makes the browser scroll it
  // fully into view — which on any screen taller than the viewport means
  // scrolling the toolbar off the top on arrival (61px, measured on
  // /clubs/new). Screens that show a loading state first were hiding the bug:
  // they were short when the focus landed. The focus cue is what matters here,
  // not the scroll position.
  useEffect(() => {
    contentRef.current?.focus({ preventScroll: true });
  }, [pathname]);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Skip link. It takes the amber fill because it is an action and nothing
          else — it exists only to be activated, it is invisible until a
          keyboard user deliberately focuses it, and at most one renders at a
          time, so it can never become the pattern or ornament amber's category
          rule forbids. The alternative (a neutral `tile`/`popover` chip) would
          make the app's least discoverable affordance also its quietest, and
          the app has no shared focus-visible treatment yet
          (MysteryMixClub-qz8d), so this control cannot lean on a ring to
          announce itself — it has to carry its own visibility. `rounded-hair`
          rather than the literal 2px it had: it renders as a button, and the
          guide gives buttons the inner-element radius. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-hair focus:bg-accent focus:px-4 focus:py-2 focus:font-mono focus:text-label focus:uppercase focus:tracking-mono focus:text-accent-foreground"
      >
        skip to content
      </a>
      <TopNav back={navBack ?? undefined} />
      <div id="main-content" ref={contentRef} tabIndex={-1} className="flex flex-1 flex-col outline-none">
        <Outlet context={{ setNavBack: setNavBackCb } satisfies AuthedOutletContext} />
      </div>
    </div>
  );
}

/** Access the authed layout's outlet context (the nav-back setter). */
export function useAuthedLayout(): AuthedOutletContext {
  return useOutletContext<AuthedOutletContext>();
}

/**
 * Declare the shared nav's contextual back affordance for the lifetime of a
 * screen. Pass the target once it's known (null while it isn't); the link clears
 * automatically on unmount so it never leaks onto the next screen.
 */
export function useNavBack(back: NavBack | null): void {
  const { setNavBack } = useAuthedLayout();
  const to = back?.to ?? null;
  const label = back?.label ?? null;
  useEffect(() => {
    setNavBack(to && label ? { to, label } : null);
    return () => setNavBack(null);
  }, [setNavBack, to, label]);
}
