import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AdminRoute } from "./AdminRoute";
import {
  ApiError,
  adminCreateInvite,
  adminDeleteUser,
  adminInviteFromWaitlist,
  adminListWaitlist,
  adminSearchUsers,
} from "../services/api";
import type { AdminUser, Invite, WaitlistEntry } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    adminSearchUsers: vi.fn(),
    adminDeleteUser: vi.fn(),
    adminCreateInvite: vi.fn(),
    adminListWaitlist: vi.fn(),
    adminInviteFromWaitlist: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockSearch = vi.mocked(adminSearchUsers);
const mockDelete = vi.mocked(adminDeleteUser);
const mockCreateInvite = vi.mocked(adminCreateInvite);
const mockListWaitlist = vi.mocked(adminListWaitlist);
const mockInviteFromWaitlist = vi.mocked(adminInviteFromWaitlist);
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
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
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

function platformInviteWith(overrides: Partial<Invite> = {}): Invite {
  return {
    id: "invite-1",
    club_id: null,
    token: "plat-tok-123",
    created_by: "admin-1",
    created_at: "2026-07-15T00:00:00Z",
    expires_at: "2026-07-17T00:00:00Z",
    ...overrides,
  };
}

function waitlistEntryWith(overrides: Partial<WaitlistEntry> = {}): WaitlistEntry {
  return {
    id: "wl-1",
    email: "waiting@example.com",
    created_at: "2026-07-15T00:00:00Z",
    invited_at: null,
    invited_by: null,
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
    mockListWaitlist.mockResolvedValue([]);
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

  describe("platform invite (MYS-182)", () => {
    it("generate calls the API and shows the shareable link", async () => {
      mockCreateInvite.mockResolvedValue(platformInviteWith());
      const user = userEvent.setup();

      renderAdmin();

      await user.click(screen.getByRole("button", { name: /^generate invite$/i }));

      expect(mockCreateInvite).toHaveBeenCalledTimes(1);
      const linkField = await screen.findByLabelText<HTMLInputElement>(/share link/i);
      expect(linkField.value).toContain("/invite/plat-tok-123");
      // The generate button is replaced by the share UI, not shown alongside it.
      expect(
        screen.queryByRole("button", { name: /^generate invite$/i }),
      ).not.toBeInTheDocument();
    });

    it("a failed generate shows a calm message and leaves the button in place", async () => {
      mockCreateInvite.mockRejectedValue(new ApiError(403, "not authorized"));
      const user = userEvent.setup();

      renderAdmin();

      await user.click(screen.getByRole("button", { name: /^generate invite$/i }));

      expect(await screen.findByText(/not authorized/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^generate invite$/i })).toBeInTheDocument();
    });
  });

  describe("waitlist (MYS-215, temporary)", () => {
    it("empty state shows a calm message", async () => {
      renderAdmin();
      expect(await screen.findByText(/no one on the waitlist yet/i)).toBeInTheDocument();
    });

    it("lists entries with join date, and unmarked entries offer 'invite'", async () => {
      mockListWaitlist.mockResolvedValue([waitlistEntryWith({ email: "fan@example.com" })]);
      renderAdmin();

      expect(await screen.findByText("fan@example.com")).toBeInTheDocument();
      expect(screen.getByText(/joined/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^invite$/i })).toBeInTheDocument();
    });

    it("an already-invited entry shows when, and offers 'resend' instead of 'invite'", async () => {
      mockListWaitlist.mockResolvedValue([
        waitlistEntryWith({ invited_at: "2026-07-16T00:00:00Z" }),
      ]);
      renderAdmin();

      await screen.findByText("waiting@example.com");
      expect(screen.getByText(/invited/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^resend$/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^invite$/i })).not.toBeInTheDocument();
    });

    it("clicking invite calls the API and updates that row to invited", async () => {
      mockListWaitlist.mockResolvedValue([waitlistEntryWith()]);
      mockInviteFromWaitlist.mockResolvedValue(
        waitlistEntryWith({ invited_at: "2026-07-21T00:00:00Z", invited_by: "admin-1" }),
      );
      const user = userEvent.setup();
      renderAdmin();

      await screen.findByText("waiting@example.com");
      await user.click(screen.getByRole("button", { name: /^invite$/i }));

      expect(mockInviteFromWaitlist).toHaveBeenCalledWith("wl-1");
      expect(await screen.findByRole("button", { name: /^resend$/i })).toBeInTheDocument();
    });

    it("a failed invite attempt shows a calm message and leaves the row unmarked", async () => {
      mockListWaitlist.mockResolvedValue([waitlistEntryWith()]);
      mockInviteFromWaitlist.mockRejectedValue(new ApiError(404, "waitlist entry not found"));
      const user = userEvent.setup();
      renderAdmin();

      await screen.findByText("waiting@example.com");
      await user.click(screen.getByRole("button", { name: /^invite$/i }));

      expect(await screen.findByText(/waitlist entry not found/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^invite$/i })).toBeInTheDocument();
    });
  });
});
