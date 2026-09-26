import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  getMe,
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refreshSession,
  setStoredAccessToken,
} from "../services/api";
import { waitUntilOnline } from "../lib/connectivity";
import { AuthContext, type AuthContextValue, type AuthStatus, type ProfileStatus } from "./useAuth";
import {
  invalidatePushSession,
  nativePushAvailable,
  onAppResume,
  openPushSession,
  syncPushRegistration,
  unregisterCurrentDevice,
} from "../ios/push";

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
  // Identifies the current profile load. clear() bumps it so a getMe() still in
  // flight when the session ends cannot apply its result to the next session.
  const profileLoadId = useRef(0);

  const setAccessToken = useCallback((next: string) => {
    // Every login is a new session with its own profile. Usually clear() has
    // already reset this, but a login that replaces a live session (a magic
    // link opened while another account is signed in) would otherwise keep the
    // previous account's profile and user id (MysteryMixClub-4vii.32).
    didLoadProfile.current = false;
    profileLoadId.current += 1;
    setStoredAccessToken(next);
    setToken(next);
    setStatus("authenticated");
  }, []);

  const clear = useCallback(() => {
    // A later login in the same launch (logout is client-side navigation, not a
    // reload) must load its own profile: without this reset the guard below
    // stays set forever and the new session never gets a userId, a display
    // name, or an onboarding check (MysteryMixClub-4vii.32).
    didLoadProfile.current = false;
    profileLoadId.current += 1;
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
      // No network is not the same as no session (MysteryMixClub-ga4y):
      // stay "loading" (the offline screen covers it) and try again once the
      // connection is back, instead of dropping to the sign-in form.
      let result = await refreshSession();
      while (result.kind === "offline") {
        await waitUntilOnline();
        result = await refreshSession();
      }
      if (result.kind === "ok") {
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
  // resets the once-per-session guard and bumps profileLoadId, so a later login
  // loads its own profile and a stale resolution from a session we've since
  // cleared is dropped.
  useEffect(() => {
    if (token === null || didLoadProfile.current) return;
    didLoadProfile.current = true;
    const loadId = profileLoadId.current;
    setProfileStatus("loading");

    void (async () => {
      try {
        const profile = await getMe();
        // The session that asked for this profile has ended (or been replaced).
        if (loadId !== profileLoadId.current) return;
        setDisplayName(profile.display_name);
        setEmail(profile.email);
        setUserId(profile.id);
        setIsPlatformAdmin(profile.is_platform_admin);
        setPreferredService(profile.preferred_service);
        setTosAccepted(profile.tos_accepted);
        setProfileStatus("ready");
      } catch {
        if (loadId !== profileLoadId.current) return;
        clear();
      }
    })();
  }, [token, clear]);

  const logout = useCallback(async () => {
    try {
      // Best-effort, before the session that authenticates it is gone
      // (PRD IOS-04: "remove account associations on logout"). One call
      // site for every caller of logout(), rather than remembering this at
      // each (TopNav, account deletion) -- a missed unregister just leaves
      // a stale row until APNs itself reports the token dead, never a
      // user-facing failure, so it's never allowed to block the real logout.
      if (nativePushAvailable()) {
        await unregisterCurrentDevice().catch(() => {});
      }
      await apiLogout();
    } finally {
      clear();
    }
  }, [clear]);

  const logoutAll = useCallback(async () => {
    try {
      if (nativePushAvailable()) {
        await unregisterCurrentDevice().catch(() => {});
      }
      await apiLogoutAll();
    } finally {
      clear();
    }
  }, [clear]);

  const needsOnboarding =
    status === "authenticated" && profileStatus === "ready" && (displayName === "" || !tosAccepted);

  // The push session lives exactly as long as the signed-in session it belongs
  // to. Keyed on the in-memory access token, which changes on login, restore
  // and any account change (never on the silent background refreshes, which
  // only touch the api module), so its cleanup -- run on logout and before
  // the next account's session opens -- abandons any registration still in
  // flight for the account that is leaving and closes the gate so nothing can
  // start a new one for it (MysteryMixClub-4vii.32). Declared before the
  // effect below: on a fresh session React runs them in order.
  useEffect(() => {
    if (!nativePushAvailable() || token === null) return;
    openPushSession();
    return () => {
      invalidatePushSession();
    };
  }, [token]);

  // Attach this device to the signed-in account for push once the session is
  // ready -- a fresh login, a session restored from the cookie at launch, or
  // the same phone signing in as someone else -- and again each time the app
  // returns to the foreground (the user may have just granted permission in iOS
  // Settings). Only ever registers when the OS permission is already granted;
  // the one-time permission prompt stays with onboarding/Profile, so this holds
  // off until onboarding is done.
  useEffect(() => {
    if (
      !nativePushAvailable() ||
      status !== "authenticated" ||
      profileStatus !== "ready" ||
      userId === null ||
      needsOnboarding
    ) {
      return;
    }
    void syncPushRegistration();
    return onAppResume(() => {
      void syncPushRegistration();
    });
  }, [status, profileStatus, userId, needsOnboarding]);

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
