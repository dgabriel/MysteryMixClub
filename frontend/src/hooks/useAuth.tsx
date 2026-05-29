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
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const didInit = useRef(false);

  const setAccessToken = useCallback((next: string) => {
    setStoredAccessToken(next);
    setToken(next);
    setStatus("authenticated");
  }, []);

  const clear = useCallback(() => {
    setStoredAccessToken(null);
    setToken(null);
    setStatus("unauthenticated");
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

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      isAuthenticated: token !== null,
      setAccessToken,
      clear,
      logout,
      logoutAll,
    }),
    [status, token, setAccessToken, clear, logout, logoutAll],
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
