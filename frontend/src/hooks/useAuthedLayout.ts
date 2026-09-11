import { useEffect } from "react";
import { useOutletContext } from "react-router";

/** A contextual back target for the shared nav (e.g. mix → its club). */
export type NavBack = { label: string; to: string };

export type AuthedOutletContext = {
  /** Set (or clear with null) the nav's contextual back affordance. Screens that
   *  need it — currently only the mix screen — call this once they know the
   *  target; everyone else leaves it null and no back link shows. */
  setNavBack: (back: NavBack | null) => void;
};

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
