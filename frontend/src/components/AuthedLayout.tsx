import { useCallback, useEffect, useState } from "react";
import { Outlet, useOutletContext } from "react-router-dom";
import { TopNav } from "./TopNav";

/** A contextual back target for the shared nav (e.g. round → its league). */
type NavBack = { label: string; to: string };

type AuthedOutletContext = {
  /** Set (or clear with null) the nav's contextual back affordance. Screens that
   *  need it — currently only the round screen — call this once they know the
   *  target; everyone else leaves it null and no back link shows. */
  setNavBack: (back: NavBack | null) => void;
};

/**
 * Layout for every authenticated screen: renders the shared TopNav once, above
 * the routed content. Mounting the nav here (rather than per screen) guarantees
 * it appears on all authed routes and never on the pre-auth ones (login / verify
 * / onboarding / invite), which live outside this layout.
 *
 * The only per-route nav variation is the contextual "← league" link on the
 * round screen. Since a layout can't read a child route's loaded data, the child
 * pushes its back target up through the outlet context (useNavBack).
 */
export function AuthedLayout() {
  const [navBack, setNavBack] = useState<NavBack | null>(null);
  const setNavBackCb = useCallback((back: NavBack | null) => setNavBack(back), []);

  return (
    <div className="min-h-screen flex flex-col">
      <TopNav back={navBack ?? undefined} />
      <Outlet context={{ setNavBack: setNavBackCb } satisfies AuthedOutletContext} />
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
