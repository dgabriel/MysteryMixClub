import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AdminRoute } from "./AdminRoute";
import { ApiError, adminDeleteUser, adminSearchUsers } from "../services/api";
import type { AdminUser } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    adminSearchUsers: vi.fn(),
    adminDeleteUser: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockSearch = vi.mocked(adminSearchUsers);
const mockDelete = vi.mocked(adminDeleteUser);
const mockUseAuth = vi.mocked(useAuth);

function setAuth(isPlatformAdmin: boolean) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: "Ada",
    email: "ada@example.com",
    userId: "admin-1",
    isPlatformAdmin,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
  });
}

function userWith(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    id: "u-1",
    email: "target@example.com",
    display_name: "Target",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderAdmin() {
  return render(
    <MemoryRouter initialEntries={["/admin"]}>
      <Routes>
        <Route path="/admin" element={<AdminRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AdminRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth(true);
    mockSearch.mockResolvedValue([]);
  });

  it("non-admin: redirects to /home and never renders the admin page", () => {
    setAuth(false);
    renderAdmin();

    expect(screen.getByText("HOME CONTENT")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^search$/i })).not.toBeInTheDocument();
  });

  it("search: queries by email and lists matches", async () => {
    mockSearch.mockResolvedValue([userWith()]);
    const user = userEvent.setup();

    renderAdmin();

    await user.type(screen.getByLabelText(/^email$/i), "target");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    expect(mockSearch).toHaveBeenCalledWith("target");
    expect(await screen.findByText("target@example.com")).toBeInTheDocument();
    expect(screen.getByText("Target")).toBeInTheDocument();
  });

  it("search: an empty result shows a calm no-matches message", async () => {
    mockSearch.mockResolvedValue([]);
    const user = userEvent.setup();

    renderAdmin();

    await user.type(screen.getByLabelText(/^email$/i), "nobody");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByText(/no matches/i)).toBeInTheDocument();
  });

  it("delete: the confirm requires typing the exact email, then calls adminDeleteUser and drops the row", async () => {
    mockSearch.mockResolvedValue([userWith()]);
    mockDelete.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderAdmin();

    await user.type(screen.getByLabelText(/^email$/i), "target");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await screen.findByText("target@example.com");

    // Arm the confirm.
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    // The destructive button is disabled until the typed email matches exactly.
    const deleteBtn = screen.getByRole("button", { name: /^delete account$/i });
    expect(deleteBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/confirm email/i), "target@example.com");
    expect(deleteBtn).toBeEnabled();

    await user.click(deleteBtn);

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("u-1"));
    await waitFor(() =>
      expect(screen.queryByText("target@example.com")).not.toBeInTheDocument(),
    );
  });

  it("delete: a 409 self-delete shows the calm backend message and keeps the row", async () => {
    mockSearch.mockResolvedValue([userWith()]);
    mockDelete.mockRejectedValue(new ApiError(409, "you can't delete your own account"));
    const user = userEvent.setup();

    renderAdmin();

    await user.type(screen.getByLabelText(/^email$/i), "target");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await screen.findByText("target@example.com");

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.type(screen.getByLabelText(/confirm email/i), "target@example.com");
    await user.click(screen.getByRole("button", { name: /^delete account$/i }));

    expect(await screen.findByText(/you can't delete your own account/i)).toBeInTheDocument();
    expect(screen.getByText("target@example.com")).toBeInTheDocument();
  });
});
