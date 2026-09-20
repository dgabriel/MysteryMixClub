import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider } from "./AuthProvider";
import { useAuth } from "./useAuth";
import {
  getMe as apiGetMe,
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refresh as apiRefresh,
  setStoredAccessToken,
} from "../services/api";
import type { UserProfile } from "../services/api";
import {
  invalidatePushSession,
  nativePushAvailable,
  onAppResume,
  openPushSession,
  syncPushRegistration,
  unregisterCurrentDevice,
} from "../ios/push";

vi.mock("../services/api", () => ({
  refresh: vi.fn(),
  getMe: vi.fn(),
  logout: vi.fn(),
  logoutAll: vi.fn(),
  setStoredAccessToken: vi.fn(),
}));

// MysteryMixClub-4vii.27 (IOS-04): logout/logoutAll drop this device's push
// registration first, native-iOS only -- default to "not native" so the
// pre-existing tests above stay unaffected.
vi.mock("../ios/push", () => ({
  nativePushAvailable: vi.fn(),
  unregisterCurrentDevice: vi.fn(),
  syncPushRegistration: vi.fn(),
  invalidatePushSession: vi.fn(),
  openPushSession: vi.fn(),
  onAppResume: vi.fn(),
}));

const mockRefresh = vi.mocked(apiRefresh);
const mockGetMe = vi.mocked(apiGetMe);
const mockLogout = vi.mocked(apiLogout);
const mockLogoutAll = vi.mocked(apiLogoutAll);
const mockSetStored = vi.mocked(setStoredAccessToken);
const mockNativePushAvailable = vi.mocked(nativePushAvailable);
const mockUnregisterCurrentDevice = vi.mocked(unregisterCurrentDevice);
const mockSyncPushRegistration = vi.mocked(syncPushRegistration);
const mockInvalidatePushSession = vi.mocked(invalidatePushSession);
const mockOpenPushSession = vi.mocked(openPushSession);
const mockOnAppResume = vi.mocked(onAppResume);

function profileWith(displayName: string): UserProfile {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    display_name: displayName,
    email: "u@example.com",
    preferred_service: null,
    is_platform_admin: false,
    tos_accepted: true,
    has_password: false,
    google_linked: false,
    email_notifications: true,
    push_lifecycle_enabled: true,
    push_deadline_reminders_enabled: true,
  };
}

function Probe() {
  const {
    status,
    profileStatus,
    needsOnboarding,
    displayName,
    userId,
    logout,
    logoutAll,
    setAccessToken,
  } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="profile-status">{profileStatus}</span>
      <span data-testid="needs-onboarding">{String(needsOnboarding)}</span>
      <span data-testid="display-name">{displayName ?? "<null>"}</span>
      <span data-testid="user-id">{userId ?? "<null>"}</span>
      {/* Swallow rejections here: the provider clears state in a finally block
          but re-surfaces the original API rejection to the caller. The tests
          assert the cleared state; the rejection itself is expected. */}
      <button type="button" onClick={() => void logout().catch(() => {})}>
        do-logout
      </button>
      <button type="button" onClick={() => setAccessToken("second-login-token")}>
        do-login
      </button>
      <button type="button" onClick={() => void logoutAll().catch(() => {})}>
        do-logout-all
      </button>
    </div>
  );
}

function renderWithProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

// Same as renderWithProvider, but wrapped in <StrictMode> so React 18
// double-invokes the on-mount effect (mount → cleanup → mount) in development.
// This reproduces the condition that previously stranded `status` on "loading":
// an effect-cleanup discard flag would drop the single refresh result. RTL's
// render does NOT add StrictMode on its own, so the explicit wrap is required.
function renderWithProviderStrict() {
  return render(
    <StrictMode>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </StrictMode>,
  );
}

describe("AuthProvider / useAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: an authenticated session loads an already-onboarded profile, so
    // the profile-load effect that follows a successful refresh resolves to a
    // ready, non-empty name. Tests that care about onboarding override this.
    mockGetMe.mockResolvedValue(profileWith("ada"));
    mockNativePushAvailable.mockReturnValue(false);
    mockSyncPushRegistration.mockResolvedValue("idle");
    mockOnAppResume.mockReturnValue(() => {});
  });

  it("calls refresh exactly once on mount", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it("on-mount refresh success → status authenticated and token mirrored to api module", async () => {
    mockRefresh.mockResolvedValue({ access_token: "restored-token" });
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(mockSetStored).toHaveBeenCalledWith("restored-token");
  });

  it("on-mount refresh returning null → status unauthenticated", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockSetStored).toHaveBeenCalledWith(null);
  });

  it("logout() calls the API then clears (status → unauthenticated)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogout.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockLogout).toHaveBeenCalledTimes(1);
    expect(mockSetStored).toHaveBeenLastCalledWith(null);
  });

  it("logout() still clears even when the API call rejects", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogout.mockRejectedValue(new Error("server error"));
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("logoutAll() calls the API then clears (status → unauthenticated)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogoutAll.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "do-logout-all" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockLogoutAll).toHaveBeenCalledTimes(1);
  });

  it("logoutAll() still clears even when the API call rejects", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogoutAll.mockRejectedValue(new Error("server error"));
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

    await user.click(screen.getByRole("button", { name: "do-logout-all" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(mockLogoutAll).toHaveBeenCalledTimes(1);
  });

  // --- Regression: StrictMode double-invoke (MYS-10) ---------------------
  // The bug: under StrictMode the on-mount effect ran mount → cleanup → mount;
  // a flag cleared in cleanup discarded the single refresh result, so `status`
  // stayed "loading" forever. These lock that down by rendering inside
  // <StrictMode> and proving status always resolves away from "loading".

  it("StrictMode: refresh success resolves status to authenticated (never stuck loading)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "restored-token" });
    renderWithProviderStrict();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(screen.getByTestId("status")).not.toHaveTextContent("loading");
    expect(mockSetStored).toHaveBeenCalledWith("restored-token");
  });

  it("StrictMode: refresh returning null resolves status to unauthenticated (never stuck loading)", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProviderStrict();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("status")).not.toHaveTextContent("loading");
    expect(mockSetStored).toHaveBeenCalledWith(null);
  });

  it("StrictMode: refresh is called exactly once despite the double-invoke", async () => {
    mockRefresh.mockResolvedValue({ access_token: "restored-token" });
    renderWithProviderStrict();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  // --- Profile load + onboarding gate (MYS-27) ---------------------------
  // After a token lands (on-mount refresh or verify), the provider fetches the
  // profile so the onboarding gate can read display_name. An empty name is the
  // not-yet-onboarded sentinel; a non-empty one means onboarded.

  it("profile load: empty display_name → needsOnboarding true, profile ready", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockResolvedValue(profileWith(""));
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("true");
    expect(mockGetMe).toHaveBeenCalledTimes(1);
  });

  it("profile load: non-empty display_name → needsOnboarding false, name exposed", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockResolvedValue(profileWith("Ada"));
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("false");
    expect(screen.getByTestId("display-name")).toHaveTextContent("Ada");
  });

  it("profile load failure → session cleared (unauthenticated, profile idle)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockRejectedValue(new Error("401"));
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("profile-status")).toHaveTextContent("idle");
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("false");
  });

  it("profile is fetched exactly once per session", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"));
    expect(mockGetMe).toHaveBeenCalledTimes(1);
  });

  // --- userId capture (MYS-15) -------------------------------------------
  // The same profile fetch that populates display_name also captures the user's
  // id, so club routes can compare it against club.organizer_id to decide
  // organizer controls. It is null before the profile loads and is reset to null
  // by clear() (logout / logout-all).

  it("userId: null before the profile loads", () => {
    // A pending refresh keeps status loading and the profile fetch from running,
    // so userId must still be the null sentinel.
    mockRefresh.mockReturnValue(new Promise(() => {}));
    renderWithProvider();

    expect(screen.getByTestId("user-id")).toHaveTextContent("<null>");
  });

  it("userId: equals the mocked profile id once the profile loads", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockResolvedValue(profileWith("Ada"));
    renderWithProvider();

    await waitFor(() => expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"));
    expect(screen.getByTestId("user-id")).toHaveTextContent("11111111-1111-1111-1111-111111111111");
  });

  it("userId: reset to null after logout clears the session", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockResolvedValue(profileWith("Ada"));
    mockLogout.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId("user-id")).toHaveTextContent(
        "11111111-1111-1111-1111-111111111111",
      ),
    );

    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"));
    expect(screen.getByTestId("user-id")).toHaveTextContent("<null>");
  });

  it("useAuth throws when used outside an AuthProvider", () => {
    // Suppress the expected React error boundary console noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/useAuth must be used within an AuthProvider/);
    spy.mockRestore();
  });

  describe("push registration cleanup on logout (MysteryMixClub-4vii.27, IOS-04)", () => {
    it("logout() drops this device's push registration before calling the API, on native iOS", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(true);
      mockUnregisterCurrentDevice.mockResolvedValue(undefined);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

      await user.click(screen.getByRole("button", { name: "do-logout" }));

      await waitFor(() =>
        expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
      );
      expect(mockUnregisterCurrentDevice).toHaveBeenCalledOnce();
      expect(mockLogout).toHaveBeenCalledTimes(1);
    });

    it("logout() never touches push on web", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(false);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

      await user.click(screen.getByRole("button", { name: "do-logout" }));

      await waitFor(() =>
        expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
      );
      expect(mockUnregisterCurrentDevice).not.toHaveBeenCalled();
    });

    it("logout() still completes even when the push cleanup rejects", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(true);
      mockUnregisterCurrentDevice.mockRejectedValue(new Error("network error"));
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

      await user.click(screen.getByRole("button", { name: "do-logout" }));

      await waitFor(() =>
        expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
      );
      expect(mockLogout).toHaveBeenCalledTimes(1);
    });

    it("logoutAll() drops this device's push registration before calling the API, on native iOS", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogoutAll.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(true);
      mockUnregisterCurrentDevice.mockResolvedValue(undefined);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));

      await user.click(screen.getByRole("button", { name: "do-logout-all" }));

      await waitFor(() =>
        expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
      );
      expect(mockUnregisterCurrentDevice).toHaveBeenCalledOnce();
      expect(mockLogoutAll).toHaveBeenCalledTimes(1);
    });
  });

  describe("session lifecycle across logout and login in one launch", () => {
    it("loads the profile again when the same launch logs out and back in", async () => {
      // Client-side navigation means there is no reload between the two: the
      // profile (and so the user id everything else keys on) must be re-fetched
      // for the new session, or it stays empty until the app is relaunched.
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("user-id")).not.toHaveTextContent("<null>"));
      expect(mockGetMe).toHaveBeenCalledTimes(1);

      await user.click(screen.getByRole("button", { name: "do-logout" }));
      await waitFor(() => expect(screen.getByTestId("user-id")).toHaveTextContent("<null>"));

      mockGetMe.mockResolvedValue({
        ...profileWith("grace"),
        id: "22222222-2222-2222-2222-222222222222",
      });
      await user.click(screen.getByRole("button", { name: "do-login" }));

      await waitFor(() =>
        expect(screen.getByTestId("user-id")).toHaveTextContent(
          "22222222-2222-2222-2222-222222222222",
        ),
      );
      expect(mockGetMe).toHaveBeenCalledTimes(2);
    });
  });

  describe("push registration follows the session (MysteryMixClub-4vii.32)", () => {
    it("registers this device once a session is restored and its profile is ready, on native iOS", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);

      renderWithProvider();

      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledOnce());
      expect(screen.getByTestId("profile-status")).toHaveTextContent("ready");
    });

    it("registers again after logging out and back in, as a fresh session", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      mockUnregisterCurrentDevice.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(true);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledTimes(1));

      await user.click(screen.getByRole("button", { name: "do-logout" }));
      await waitFor(() =>
        expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
      );
      await user.click(screen.getByRole("button", { name: "do-login" }));

      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledTimes(2));
    });

    it("never touches push on web", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(false);

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"));

      expect(mockSyncPushRegistration).not.toHaveBeenCalled();
      expect(mockOnAppResume).not.toHaveBeenCalled();
    });

    it("waits until the profile has loaded", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);
      let finishProfile: (p: UserProfile) => void = () => {};
      mockGetMe.mockReturnValue(
        new Promise<UserProfile>((resolve) => {
          finishProfile = resolve;
        }),
      );

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("authenticated"));
      expect(mockSyncPushRegistration).not.toHaveBeenCalled();

      finishProfile(profileWith("ada"));
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledOnce());
    });

    it("holds off while onboarding is still needed, so the first permission prompt stays with onboarding", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);
      mockGetMe.mockResolvedValue(profileWith(""));

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("true"));

      expect(mockSyncPushRegistration).not.toHaveBeenCalled();
    });

    it("re-syncs each time the app returns to the foreground", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);
      let resumed: () => void = () => {};
      mockOnAppResume.mockImplementation((callback) => {
        resumed = callback;
        return () => {};
      });

      renderWithProvider();
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledTimes(1));

      resumed();

      expect(mockSyncPushRegistration).toHaveBeenCalledTimes(2);
    });

    it("opens the push session as soon as someone is signed in, before the profile has loaded", async () => {
      // The first permission prompt (onboarding) can register the device while
      // the profile gate is still up, so the session must already be open.
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);
      mockGetMe.mockReturnValue(new Promise(() => {}));

      renderWithProvider();

      await waitFor(() => expect(mockOpenPushSession).toHaveBeenCalledOnce());
      expect(screen.getByTestId("profile-status")).toHaveTextContent("loading");
    });

    it("treats a login that replaces a live session as an account switch: new profile, new push session", async () => {
      // No logout in between (e.g. a magic link opened while another account is
      // signed in): the previous account's profile and push registration must
      // not carry over to the new one.
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(screen.getByTestId("user-id")).not.toHaveTextContent("<null>"));
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledTimes(1));
      mockInvalidatePushSession.mockClear();
      mockOpenPushSession.mockClear();

      mockGetMe.mockResolvedValue({
        ...profileWith("grace"),
        id: "22222222-2222-2222-2222-222222222222",
      });
      await user.click(screen.getByRole("button", { name: "do-login" }));

      await waitFor(() =>
        expect(screen.getByTestId("user-id")).toHaveTextContent(
          "22222222-2222-2222-2222-222222222222",
        ),
      );
      // The old account's push session ended before the new one began...
      expect(mockInvalidatePushSession).toHaveBeenCalled();
      expect(mockOpenPushSession).toHaveBeenCalled();
      expect(mockInvalidatePushSession.mock.invocationCallOrder[0]).toBeLessThan(
        mockOpenPushSession.mock.invocationCallOrder[0],
      );
      // ...and the new account is registered for itself.
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledTimes(2));
    });

    it("does not end the push session when the profile settles or onboarding completes", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockNativePushAvailable.mockReturnValue(true);

      renderWithProvider();
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledOnce());

      expect(mockInvalidatePushSession).not.toHaveBeenCalled();
    });

    it("stops watching the foreground and invalidates the push session when the session ends", async () => {
      mockRefresh.mockResolvedValue({ access_token: "tok" });
      mockLogout.mockResolvedValue(undefined);
      mockUnregisterCurrentDevice.mockResolvedValue(undefined);
      mockNativePushAvailable.mockReturnValue(true);
      const stopWatching = vi.fn();
      mockOnAppResume.mockReturnValue(stopWatching);
      const user = userEvent.setup();

      renderWithProvider();
      await waitFor(() => expect(mockSyncPushRegistration).toHaveBeenCalledOnce());
      mockInvalidatePushSession.mockClear();

      await user.click(screen.getByRole("button", { name: "do-logout" }));

      await waitFor(() => expect(stopWatching).toHaveBeenCalled());
      expect(mockInvalidatePushSession).toHaveBeenCalled();
    });
  });
});
