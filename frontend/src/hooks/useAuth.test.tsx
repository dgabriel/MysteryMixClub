import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, useAuth } from "./useAuth";
import {
  getMe as apiGetMe,
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refresh as apiRefresh,
  setStoredAccessToken,
} from "../services/api";
import type { UserProfile } from "../services/api";

vi.mock("../services/api", () => ({
  refresh: vi.fn(),
  getMe: vi.fn(),
  logout: vi.fn(),
  logoutAll: vi.fn(),
  setStoredAccessToken: vi.fn(),
}));

const mockRefresh = vi.mocked(apiRefresh);
const mockGetMe = vi.mocked(apiGetMe);
const mockLogout = vi.mocked(apiLogout);
const mockLogoutAll = vi.mocked(apiLogoutAll);
const mockSetStored = vi.mocked(setStoredAccessToken);

function profileWith(displayName: string): UserProfile {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    display_name: displayName,
    email: "u@example.com",
    preferred_service: null,
    is_platform_admin: false,
    tos_accepted: true,
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
  });

  it("calls refresh exactly once on mount", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it("on-mount refresh success → status authenticated and token mirrored to api module", async () => {
    mockRefresh.mockResolvedValue({ access_token: "restored-token" });
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(mockSetStored).toHaveBeenCalledWith("restored-token");
  });

  it("on-mount refresh returning null → status unauthenticated", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(mockSetStored).toHaveBeenCalledWith(null);
  });

  it("logout() calls the API then clears (status → unauthenticated)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogout.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(mockLogout).toHaveBeenCalledTimes(1);
    expect(mockSetStored).toHaveBeenLastCalledWith(null);
  });

  it("logout() still clears even when the API call rejects", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogout.mockRejectedValue(new Error("server error"));
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "do-logout" }));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(mockLogout).toHaveBeenCalledTimes(1);
  });

  it("logoutAll() calls the API then clears (status → unauthenticated)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogoutAll.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "do-logout-all" }));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(mockLogoutAll).toHaveBeenCalledTimes(1);
  });

  it("logoutAll() still clears even when the API call rejects", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockLogoutAll.mockRejectedValue(new Error("server error"));
    const user = userEvent.setup();

    renderWithProvider();
    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );

    await user.click(screen.getByRole("button", { name: "do-logout-all" }));

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
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

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
    expect(screen.getByTestId("status")).not.toHaveTextContent("loading");
    expect(mockSetStored).toHaveBeenCalledWith("restored-token");
  });

  it("StrictMode: refresh returning null resolves status to unauthenticated (never stuck loading)", async () => {
    mockRefresh.mockResolvedValue(null);
    renderWithProviderStrict();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(screen.getByTestId("status")).not.toHaveTextContent("loading");
    expect(mockSetStored).toHaveBeenCalledWith(null);
  });

  it("StrictMode: refresh is called exactly once despite the double-invoke", async () => {
    mockRefresh.mockResolvedValue({ access_token: "restored-token" });
    renderWithProviderStrict();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("authenticated"),
    );
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

    await waitFor(() =>
      expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"),
    );
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("true");
    expect(mockGetMe).toHaveBeenCalledTimes(1);
  });

  it("profile load: non-empty display_name → needsOnboarding false, name exposed", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockResolvedValue(profileWith("Ada"));
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"),
    );
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("false");
    expect(screen.getByTestId("display-name")).toHaveTextContent("Ada");
  });

  it("profile load failure → session cleared (unauthenticated, profile idle)", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    mockGetMe.mockRejectedValue(new Error("401"));
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(screen.getByTestId("profile-status")).toHaveTextContent("idle");
    expect(screen.getByTestId("needs-onboarding")).toHaveTextContent("false");
  });

  it("profile is fetched exactly once per session", async () => {
    mockRefresh.mockResolvedValue({ access_token: "tok" });
    renderWithProvider();

    await waitFor(() =>
      expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"),
    );
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

    await waitFor(() =>
      expect(screen.getByTestId("profile-status")).toHaveTextContent("ready"),
    );
    expect(screen.getByTestId("user-id")).toHaveTextContent(
      "11111111-1111-1111-1111-111111111111",
    );
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

    await waitFor(() =>
      expect(screen.getByTestId("status")).toHaveTextContent("unauthenticated"),
    );
    expect(screen.getByTestId("user-id")).toHaveTextContent("<null>");
  });

  it("useAuth throws when used outside an AuthProvider", () => {
    // Suppress the expected React error boundary console noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(
      /useAuth must be used within an AuthProvider/,
    );
    spy.mockRestore();
  });
});
