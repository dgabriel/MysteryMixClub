import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, useAuth } from "./useAuth";
import {
  logout as apiLogout,
  logoutAll as apiLogoutAll,
  refresh as apiRefresh,
  setStoredAccessToken,
} from "../services/api";

vi.mock("../services/api", () => ({
  refresh: vi.fn(),
  logout: vi.fn(),
  logoutAll: vi.fn(),
  setStoredAccessToken: vi.fn(),
}));

const mockRefresh = vi.mocked(apiRefresh);
const mockLogout = vi.mocked(apiLogout);
const mockLogoutAll = vi.mocked(apiLogoutAll);
const mockSetStored = vi.mocked(setStoredAccessToken);

function Probe() {
  const { status, logout, logoutAll } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
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

describe("AuthProvider / useAuth", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("useAuth throws when used outside an AuthProvider", () => {
    // Suppress the expected React error boundary console noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(
      /useAuth must be used within an AuthProvider/,
    );
    spy.mockRestore();
  });
});
