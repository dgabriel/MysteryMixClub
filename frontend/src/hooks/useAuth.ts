import { createContext, useContext } from "react";

/**
 * Auth context. The access token is held in memory only (React state, mirrored
 * to the api module's in-memory variable so the request wrapper can read it).
 * It is NEVER persisted to localStorage / sessionStorage / a client-set cookie
 * (technical-design §5 / §9).
 *
 * The provider (`AuthProvider`, in `./AuthProvider.tsx` — split out so this
 * file exports only non-component values, satisfying
 * react-refresh/only-export-components) attempts one silent refresh against
 * the HttpOnly refresh cookie on mount. This is what lets a PWA reopened from
 * the home screen land logged-in without a fresh magic link.
 */

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";
export type ProfileStatus = "idle" | "loading" | "ready";

export type AuthContextValue = {
  status: AuthStatus;
  isAuthenticated: boolean;
  /** Store a freshly issued access token (e.g. after magic-link verify). */
  setAccessToken: (token: string) => void;
  /** Drop the in-memory token and mark the session unauthenticated. */
  clear: () => void;
  /** Invalidate the current session server-side, then clear locally. */
  logout: () => Promise<void>;
  /** Invalidate all sessions server-side, then clear locally. */
  logoutAll: () => Promise<void>;
  /** Current user's display name once the profile loads; null while unloaded. */
  displayName: string | null;
  /** Current user's email once the profile loads; null while unloaded. Shown on
   *  the profile screen as read-only account identity. */
  email: string | null;
  /** Current user's id once the profile loads; null while unloaded. Club
   *  routes compare it against club.organizer_id to gate organizer controls. */
  userId: string | null;
  /** True once the profile loads and the user is a platform admin. Gates the
   *  /admin route and its nav entry; false while the profile is unloaded. */
  isPlatformAdmin: boolean;
  /** Lifecycle of the profile fetch that follows authentication. */
  profileStatus: ProfileStatus;
  /** True only when authenticated and profile loaded, and either the display
   *  name is the empty-string sentinel (never onboarded) or the Terms of
   *  Service / Privacy Policy haven't been accepted yet (MYS-183) — covers
   *  both a brand-new user and an already-onboarded user who predates the
   *  consent requirement. Either case routes to /onboarding. */
  needsOnboarding: boolean;
  /** True once the current profile has accepted the Terms/Privacy Policy. */
  tosAccepted: boolean;
  /** Apply a new display name locally (after a successful PATCH) so the
   *  onboarding gate flips false without a refetch. */
  applyDisplayName: (name: string) => void;
  /** Apply Terms/Privacy acceptance locally (after a successful PATCH) so the
   *  consent gate flips false without a refetch. */
  applyTosAccepted: () => void;
  /** User's preferred streaming service from their profile; null if unset. */
  preferredService: string | null;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
