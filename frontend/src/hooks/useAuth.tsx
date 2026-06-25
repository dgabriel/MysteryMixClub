import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  getMe,
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refresh as apiRefresh,
  setStoredAccessToken,
} from "../services/api";

/**
 * Auth context. The access token is held in memory only (React state, mirrored
 * to the api module's in-memory variable so the request wrapper can read it).
 * It is NEVER persisted to localStorage / sessionStorage / a client-set cookie
 * (technical-design §5 / §9).
 *
 * On mount we attempt one silent refresh against the HttpOnly refresh cookie.
 * This is what lets a PWA reopened from the home screen land logged-in without a
 * fresh magic link.
 */

type AuthStatus = "loading" | "authenticated" | "unauthenticated";
type ProfileStatus = "idle" | "loading" | "ready";

type AuthContextValue = {
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
  /** Current user's id once the profile loads; null while unloaded. League
   *  routes compare it against league.organizer_id to gate organizer controls. */
  userId: string | null;
  /** True once the profile loads and the user is a platform admin. Gates the
   *  /admin route and its nav entry; false while the profile is unloaded. */
  isPlatformAdmin: boolean;
  /** Lifecycle of the profile fetch that follows authentication. */
  profileStatus: ProfileStatus;
  /** True only when authenticated, profile loaded, and the name is the
   *  empty-string sentinel — i.e. the user has not yet onboarded. */
  needsOnboarding: boolean;
  /** Apply a new display name locally (after a successful PATCH) so the
   *  onboarding gate flips false without a refetch. */
  applyDisplayName: (name: string) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [profileStatus, setProfileStatus] = useState<ProfileStatus>("idle");
  const didInit = useRef(false);
  const didLoadProfile = useRef(false);

  const setAccessToken = useCallback((next: string) => {
    setStoredAccessToken(next);
    setToken(next);
    setStatus("authenticated");
  }, []);

  const clear = useCallback(() => {
    setStoredAccessToken(null);
    setToken(null);
    setStatus("unauthenticated");
    setDisplayName(null);
    setUserId(null);
    setIsPlatformAdmin(false);
    setProfileStatus("idle");
  }, []);

  const applyDisplayName = useCallback((name: string) => {
    setDisplayName(name);
  }, []);

  // On mount: attempt a silent refresh to restore the session from the cookie.
  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke in development.
    if (didInit.current) return;
    didInit.current = true;

    // We refresh exactly once (guarded by didInit above). The result must always
    // be applied so status resolves away from "loading" — we deliberately do NOT
    // gate it on an effect-cleanup flag, because StrictMode runs cleanup before
    // this one call resolves, which would otherwise leave status stuck loading.
    void (async () => {
      const result = await apiRefresh();
      if (result) {
        setStoredAccessToken(result.access_token);
        setToken(result.access_token);
        setStatus("authenticated");
      } else {
        setStoredAccessToken(null);
        setToken(null);
        setStatus("unauthenticated");
      }
    })();
  }, []);

  // Once a token is in memory (from on-mount refresh OR magic-link verify),
  // load the profile so the onboarding gate can read the display name. A GET is
  // idempotent, so the StrictMode double-invoke is harmless; the didLoadProfile
  // ref still keeps us to a single fetch per session. On failure we treat the
  // session as unauthenticated — authenticatedRequest already attempted a silent
  // refresh, so a failure here means there is no recoverable session. clear()
  // resets the profile refs implicitly via its state changes; the guard below
  // prevents a stale resolution from overwriting a session we've since cleared.
  useEffect(() => {
    if (token === null || didLoadProfile.current) return;
    didLoadProfile.current = true;
    setProfileStatus("loading");

    void (async () => {
      try {
        const profile = await getMe();
        setDisplayName(profile.display_name);
        setUserId(profile.id);
        setIsPlatformAdmin(profile.is_platform_admin);
        setProfileStatus("ready");
      } catch {
        didLoadProfile.current = false;
        clear();
      }
    })();
  }, [token, clear]);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      clear();
    }
  }, [clear]);

  const logoutAll = useCallback(async () => {
    try {
      await apiLogoutAll();
    } finally {
      clear();
    }
  }, [clear]);

  const needsOnboarding =
    status === "authenticated" && profileStatus === "ready" && displayName === "";

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      isAuthenticated: token !== null,
      setAccessToken,
      clear,
      logout,
      logoutAll,
      displayName,
      userId,
      isPlatformAdmin,
      profileStatus,
      needsOnboarding,
      applyDisplayName,
    }),
    [
      status,
      token,
      setAccessToken,
      clear,
      logout,
      logoutAll,
      displayName,
      userId,
      isPlatformAdmin,
      profileStatus,
      needsOnboarding,
      applyDisplayName,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
