import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProfileRoute } from "./ProfileRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, getLeagues, getMe, updateDisplayName } from "../services/api";
import type { League, UserProfile } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getLeagues: vi.fn(),
    getMe: vi.fn(),
    updateDisplayName: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetLeagues = vi.mocked(getLeagues);
const mockGetMe = vi.mocked(getMe);
const mockUpdateDisplayName = vi.mocked(updateDisplayName);
const mockUseAuth = vi.mocked(useAuth);
const applyDisplayName = vi.fn();
const mockLogoutAll = vi.fn();

function setAuth(displayName: string | null = "Ada") {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: mockLogoutAll,
    displayName,
    email: "ada@example.com",
    userId: "user-1",
    isPlatformAdmin: false,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName,
    preferredService: null,
  });
}

function leagueWith(overrides: Partial<League> = {}): League {
  return {
    id: "league-1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "org-1",
    total_rounds: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_round: 6,
    state: "complete",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    created_at: "2026-01-01T00:00:00Z",
    completed_at: "2026-02-01T00:00:00Z",
    ...overrides,
  };
}

function profileWith(displayName: string): UserProfile {
  return {
    id: "user-1",
    display_name: displayName,
    email: "ada@example.com",
    preferred_service: null,
    is_platform_admin: false,
  };
}

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/profile"]}>
      <Routes>
        {/* Mirror production: the profile route lives under AuthedLayout, which
            renders the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/profile" element={<ProfileRoute />} />
        </Route>
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/leagues/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProfileRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth("Ada");
    mockGetLeagues.mockResolvedValue([]);
    mockGetMe.mockResolvedValue(profileWith("Ada"));
  });

  it("renders the current display name and only the completed leagues, newest first", async () => {
    mockGetLeagues.mockResolvedValue([
      leagueWith({ id: "active-1", name: "In Progress", state: "active", completed_at: null }),
      leagueWith({ id: "old", name: "Old Mix", completed_at: "2026-01-15T00:00:00Z" }),
      leagueWith({ id: "new", name: "New Mix", completed_at: "2026-03-15T00:00:00Z" }),
    ]);

    renderProfile();

    // Active league is excluded from the archive.
    expect(await screen.findByText("archived (2)")).toBeInTheDocument();
    expect(screen.queryByText("In Progress")).not.toBeInTheDocument();

    // Account email shown read-only from the auth context.
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();

    // Name field seeded from the auth context.
    const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
    expect(nameInput.value).toBe("Ada");

    // Newest-completed appears before the older one.
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(["New Mix", "Old Mix"]);
  });

  it("empty archive: shows a calm note", async () => {
    mockGetLeagues.mockResolvedValue([
      leagueWith({ state: "active", completed_at: null }),
    ]);

    renderProfile();

    expect(await screen.findByText(/no completed leagues yet/i)).toBeInTheDocument();
  });

  it("save: a changed name calls updateDisplayName, applies it, and acknowledges", async () => {
    mockUpdateDisplayName.mockResolvedValue(profileWith("Ada Lovelace"));
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Ada Lovelace");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateDisplayName).toHaveBeenCalledWith("Ada Lovelace");
    await waitFor(() => expect(applyDisplayName).toHaveBeenCalledWith("Ada Lovelace"));
    expect(await screen.findByText("saved")).toBeInTheDocument();
  });

  it("save: an unchanged name does not call updateDisplayName", async () => {
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateDisplayName).not.toHaveBeenCalled();
  });

  it("save: a failure shows a calm retryable error", async () => {
    mockUpdateDisplayName.mockRejectedValue(new ApiError(409, "name taken"));
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Taken");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/name taken/i)).toBeInTheDocument();
  });

  it("archived league is linkable to its league home", async () => {
    mockGetLeagues.mockResolvedValue([leagueWith({ id: "league-9", name: "Click Me" })]);
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText("Click Me");

    await user.click(screen.getByText("Click Me"));

    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
  });

  it("load failure: shows a calm error", async () => {
    mockGetLeagues.mockRejectedValue(new ApiError(500, "boom"));

    renderProfile();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("nav: the TopNav home link navigates to /home", async () => {
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    // Two "home" controls in the TopNav (ring mark + text link); either routes home.
    await user.click(screen.getAllByRole("button", { name: /^home$/i })[1]);

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("security: log out of all devices button calls logoutAll", async () => {
    mockLogoutAll.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderProfile();
    await screen.findByText(/archived/i);

    await user.click(screen.getByRole("button", { name: /log out of all devices/i }));

    expect(mockLogoutAll).toHaveBeenCalledOnce();
  });
});
