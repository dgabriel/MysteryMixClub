import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ResetPasswordRoute } from "./ResetPasswordRoute";
import { ApiError, resetPassword } from "../services/api";

// Mock the API module (no network). ApiError stays real so the route's
// instanceof-based status mapping works.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    resetPassword: vi.fn(),
  };
});

const mockResetPassword = vi.mocked(resetPassword);

function renderAt(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/auth/reset-password" element={<ResetPasswordRoute />} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  password: string,
  confirm: string,
) {
  await user.type(screen.getByLabelText(/^new password$/i), password);
  await user.type(screen.getByLabelText(/^confirm password$/i), confirm);
  await user.click(screen.getByRole("button", { name: /save password/i }));
}

describe("ResetPasswordRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("happy path: submits the token with the new password, then points at sign-in", async () => {
    mockResetPassword.mockResolvedValue({ message: "password updated" });
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=tok-1");
    await fillAndSubmit(user, "long-enough-pw", "long-enough-pw");

    await waitFor(() => expect(mockResetPassword).toHaveBeenCalledWith("tok-1", "long-enough-pw"));
    expect(await screen.findByText("password updated")).toBeInTheDocument();

    // No session comes back — the reset evicts every session, so the only way
    // forward is signing in again.
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("a missing token shows the calm link-failed state without any form", () => {
    renderAt("/auth/reset-password");

    expect(screen.getByText(/that link didn’t work/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^new password$/i)).not.toBeInTheDocument();
    expect(mockResetPassword).not.toHaveBeenCalled();
  });

  it("a 401 (spent or expired token) shows the same calm link-failed state", async () => {
    mockResetPassword.mockRejectedValue(new ApiError(401, "invalid or expired link"));
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=stale");
    await fillAndSubmit(user, "long-enough-pw", "long-enough-pw");

    expect(await screen.findByText(/that link didn’t work/i)).toBeInTheDocument();
  });

  it("a mismatched confirmation is caught before any request", async () => {
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=tok-1");
    await fillAndSubmit(user, "long-enough-pw", "long-enough-pX");

    expect(await screen.findByRole("alert")).toHaveTextContent(/these don't match/i);
    expect(mockResetPassword).not.toHaveBeenCalled();
  });

  it("a transport failure is a screen-level error, not a password field error", async () => {
    mockResetPassword.mockRejectedValue(new Error("network down"));
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=tok-1");
    await fillAndSubmit(user, "long-enough-pw", "long-enough-pw");

    // The request never landed, so the password is not what's wrong with it.
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't save that right now/i);
    expect(screen.getByLabelText(/^new password$/i)).not.toHaveAttribute("aria-invalid", "true");
    // Still on the form, not bounced to the link-failed state.
    expect(screen.getByRole("button", { name: /save password/i })).toBeInTheDocument();
  });

  it("the new password can be revealed to check what was typed", async () => {
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=tok-1");
    expect(screen.getByLabelText(/^new password$/i)).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: /show password/i }));
    expect(screen.getByLabelText(/^new password$/i)).toHaveAttribute("type", "text");
  });

  it("a short password is caught before any request", async () => {
    const user = userEvent.setup();

    renderAt("/auth/reset-password?token=tok-1");
    await fillAndSubmit(user, "short", "short");

    expect(await screen.findByRole("alert")).toHaveTextContent(/at least 8 characters/i);
    expect(mockResetPassword).not.toHaveBeenCalled();
  });
});
