import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { VerifyRoute } from "./VerifyRoute";
import { verifyToken } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network).
vi.mock("../services/api", () => ({
  verifyToken: vi.fn(),
}));

// Mock useAuth so we can observe setAccessToken without a real provider.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockVerifyToken = vi.mocked(verifyToken);
const mockUseAuth = vi.mocked(useAuth);
const setAccessToken = vi.fn();

function renderAt(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/auth/verify" element={<VerifyRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("VerifyRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAuth.mockReturnValue({
      status: "loading",
      isAuthenticated: false,
      setAccessToken,
      clear: vi.fn(),
      logout: vi.fn(),
      logoutAll: vi.fn(),
    });
  });

  it("happy path: verifies the token, stores the access token, and navigates to /home", async () => {
    mockVerifyToken.mockResolvedValue({ access_token: "tok-123" });

    renderAt("/auth/verify?token=abc");

    // Navigates to /home (routed render confirms the destination renders).
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();

    expect(mockVerifyToken).toHaveBeenCalledTimes(1);
    expect(mockVerifyToken).toHaveBeenCalledWith("abc");
    expect(setAccessToken).toHaveBeenCalledWith("tok-123");
  });

  it("error path: when verifyToken rejects, renders the error state with a back-to-login affordance", async () => {
    mockVerifyToken.mockRejectedValue(new Error("expired"));

    renderAt("/auth/verify?token=bad");

    expect(await screen.findByText(/that link didn.?t work/i)).toBeInTheDocument();
    expect(setAccessToken).not.toHaveBeenCalled();

    // Back-to-login affordance present and routes to /login.
    const back = screen.getByRole("button", { name: /request a new one/i });
    const user = userEvent.setup();
    await user.click(back);
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("edge case: missing token renders the error state WITHOUT calling verifyToken", async () => {
    renderAt("/auth/verify");

    expect(await screen.findByText(/that link didn.?t work/i)).toBeInTheDocument();
    expect(mockVerifyToken).not.toHaveBeenCalled();
    expect(setAccessToken).not.toHaveBeenCalled();
  });

  it("shows the verifying state before resolution", async () => {
    // A pending promise keeps it in 'verifying'.
    let resolve!: (v: { access_token: string }) => void;
    mockVerifyToken.mockReturnValue(
      new Promise<{ access_token: string }>((r) => {
        resolve = r;
      }),
    );

    renderAt("/auth/verify?token=pending");

    expect(screen.getByText(/verifying/i)).toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();

    // Resolve to clean up the pending async work.
    resolve({ access_token: "later" });
    await waitFor(() => expect(setAccessToken).toHaveBeenCalled());
  });
});
