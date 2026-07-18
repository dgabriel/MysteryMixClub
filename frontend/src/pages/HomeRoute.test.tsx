import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { HomeRoute } from "./HomeRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, getLeagues } from "../services/api";
import type { League } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real so instanceof / status work.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    getLeagues: vi.fn(),
  };
});

// Mock useAuth so we drive displayName / logout directly.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetLeagues = vi.mocked(getLeagues);
const mockUseAuth = vi.mocked(useAuth);
const logout = vi.fn();

function leagueWith(overrides: Partial<League> = {}): League {
  return {
    id: "league-1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "22222222-2222-2222-2222-222222222222",
    total_rounds: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_round: 2,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    completed_at: null,
    ...overrides,
  };
}

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        {/* Mirror production: the route lives under AuthedLayout, which renders
            the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/home" element={<HomeRoute />} />
        </Route>
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/clubs/new" element={<div>NEW LEAGUE CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
        <Route path="/join/:token" element={<div>JOIN CONTENT</div>} />
        <Route path="/admin" element={<div>ADMIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HomeRoute (My Leagues)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    logout.mockResolvedValue(undefined);
    mockGetLeagues.mockResolvedValue([leagueWith()]);
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      setAccessToken: vi.fn(),
      clear: vi.fn(),
      logout,
      logoutAll: vi.fn(),
      displayName: "ada",
      email: "ada@example.com",
      userId: "11111111-1111-1111-1111-111111111111",
      profileStatus: "ready",
      needsOnboarding: false,
      isPlatformAdmin: false,
      applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("happy path: calls getLeagues on mount and renders the league name", async () => {
    renderHome();

    expect(await screen.findByText("Friday Mixtape")).toBeInTheDocument();
    expect(mockGetLeagues).toHaveBeenCalledTimes(1);
  });

  it("groups completed leagues below active ones under a 'completed' heading with gold accent", async () => {
    mockGetLeagues.mockResolvedValue([
      leagueWith({ id: "a1", name: "Active One", state: "active" }),
      leagueWith({ id: "c1", name: "Finished One", state: "complete", current_round: 6 }),
    ]);
    renderHome();

    const completedHeading = await screen.findByText("completed");
    const active = screen.getByText("Active One");
    const done = screen.getByText("Finished One");

    // Active league precedes the "completed" heading, which precedes the completed league.
    expect(
      active.compareDocumentPosition(completedHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      completedHeading.compareDocumentPosition(done) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Only the completed card wears the gold achievement accent.
    expect(done.closest(".border-l-gold")).not.toBeNull();
    expect(active.closest(".border-l-gold")).toBeNull();
  });

  it("empty list: renders the empty-state copy", async () => {
    mockGetLeagues.mockResolvedValue([]);
    renderHome();

    expect(await screen.findByText("no clubs yet")).toBeInTheDocument();
  });

  it("error: getLeagues rejecting surfaces a calm error via the error prop", async () => {
    mockGetLeagues.mockRejectedValue(new ApiError(500, "boom"));
    renderHome();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("create: the create-a-league action navigates to /clubs/new", async () => {
    mockGetLeagues.mockResolvedValue([]);
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByRole("button", { name: /create a club/i }));

    expect(await screen.findByText("NEW LEAGUE CONTENT")).toBeInTheDocument();
  });

  it("open: clicking a league navigates to /clubs/{id}", async () => {
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByText("Friday Mixtape"));

    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
  });

  it("logout: invokes useAuth().logout and navigates to /login", async () => {
    const user = userEvent.setup();
    renderHome();

    await screen.findByText("Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^logout$/i }));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("pending invite: a stored pendingInvitePath redirects there and clears the key", async () => {
    localStorage.setItem("pendingInvitePath", "/join/abc");
    renderHome();

    expect(await screen.findByText("JOIN CONTENT")).toBeInTheDocument();
    expect(localStorage.getItem("pendingInvitePath")).toBeNull();
  });

  it("admin nav: hidden for a non-admin", async () => {
    renderHome();

    await screen.findByText("Friday Mixtape");
    expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
  });

  it("admin nav: a platform admin gets an admin entry that routes to /admin", async () => {
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      setAccessToken: vi.fn(),
      clear: vi.fn(),
      logout,
      logoutAll: vi.fn(),
      displayName: "ada",
      email: "ada@example.com",
      userId: "11111111-1111-1111-1111-111111111111",
      profileStatus: "ready",
      needsOnboarding: false,
      isPlatformAdmin: true,
      applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
    });
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByRole("button", { name: /^admin$/i }));

    expect(await screen.findByText("ADMIN CONTENT")).toBeInTheDocument();
  });
});
