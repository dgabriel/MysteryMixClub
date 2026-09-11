import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  getMe,
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refresh as apiRefresh,
  setStoredAccessToken,
} from "../services/api";
import { AuthContext, type AuthContextValue, type AuthStatus, type ProfileStatus } from "./useAuth";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [preferredService, setPreferredService] = useState<string | null>(null);
  const [tosAccepted, setTosAccepted] = useState(false);
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
    setEmail(null);
    setUserId(null);
    setIsPlatformAdmin(false);
    setPreferredService(null);
    setTosAccepted(false);
    setProfileStatus("idle");
  }, []);

  const applyDisplayName = useCallback((name: string) => {
    setDisplayName(name);
  }, []);

  const applyTosAccepted = useCallback(() => {
    setTosAccepted(true);
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
        setEmail(profile.email);
        setUserId(profile.id);
        setIsPlatformAdmin(profile.is_platform_admin);
        setPreferredService(profile.preferred_service);
        setTosAccepted(profile.tos_accepted);
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
    status === "authenticated" &&
    profileStatus === "ready" &&
    (displayName === "" || !tosAccepted);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      isAuthenticated: token !== null,
      setAccessToken,
      clear,
      logout,
      logoutAll,
      displayName,
      email,
      userId,
      isPlatformAdmin,
      preferredService,
      tosAccepted,
      profileStatus,
      needsOnboarding,
      applyDisplayName,
      applyTosAccepted,
    }),
    [
      status,
      token,
      setAccessToken,
      clear,
      logout,
      logoutAll,
      displayName,
      email,
      userId,
      isPlatformAdmin,
      preferredService,
      tosAccepted,
      profileStatus,
      needsOnboarding,
      applyDisplayName,
      applyTosAccepted,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
