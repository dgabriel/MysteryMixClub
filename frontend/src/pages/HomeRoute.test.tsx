import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { HomeRoute } from "./HomeRoute";
import { useAuth } from "../hooks/useAuth";

vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);
const logout = vi.fn();
const logoutAll = vi.fn();

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        <Route path="/home" element={<HomeRoute />} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    logout.mockResolvedValue(undefined);
    logoutAll.mockResolvedValue(undefined);
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      setAccessToken: vi.fn(),
      clear: vi.fn(),
      logout,
      logoutAll,
    });
  });

  it("renders the signed-in shell", () => {
    renderHome();
    expect(screen.getByText("you’re in")).toBeInTheDocument();
  });

  it("logout action invokes useAuth().logout and navigates to /login", async () => {
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole("button", { name: /^logout$/i }));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(logoutAll).not.toHaveBeenCalled();
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("log-out-all action invokes useAuth().logoutAll and navigates to /login", async () => {
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole("button", { name: /log out of all devices/i }));

    expect(logoutAll).toHaveBeenCalledTimes(1);
    expect(logout).not.toHaveBeenCalled();
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("disables both actions while a logout call is in flight (busy)", async () => {
    // Keep logout pending to observe the busy state.
    let resolve!: () => void;
    logout.mockReturnValue(
      new Promise<void>((r) => {
        resolve = r;
      }),
    );
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole("button", { name: /^logout$/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^logout$/i })).toBeDisabled(),
    );
    expect(
      screen.getByRole("button", { name: /log out of all devices/i }),
    ).toBeDisabled();

    // Resolve the pending logout and wait for navigation so the trailing
    // setBusy(false) state update is flushed inside act().
    resolve();
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });
});
