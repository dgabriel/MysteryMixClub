import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { JoinLeagueRoute } from "./JoinLeagueRoute";
import { ApiError, acceptInvite, getInvitePreview } from "../services/api";
import type { InvitePreview, League } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    getInvitePreview: vi.fn(),
    acceptInvite: vi.fn(),
  };
});

// Mock useAuth so we control isAuthenticated.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetInvitePreview = vi.mocked(getInvitePreview);
const mockAcceptInvite = vi.mocked(acceptInvite);
const mockUseAuth = vi.mocked(useAuth);

function preview(): InvitePreview {
  return { league_name: "Friday Mixtape", member_count: 4 };
}

function leagueWith(id: string): League {
  return {
    id,
    name: "Friday Mixtape",
    description: null,
    organizer_id: "org-1",
    total_rounds: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_round: 0,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    default_vibe_mode: false,
    completed_at: null,
  };
}

function setAuth(isAuthenticated: boolean) {
  mockUseAuth.mockReturnValue({
    status: isAuthenticated ? "authenticated" : "unauthenticated",
    isAuthenticated,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: isAuthenticated ? "Ada" : null,
    email: isAuthenticated ? "ada@example.com" : null,
    userId: isAuthenticated ? "user-1" : null,
    profileStatus: isAuthenticated ? "ready" : "idle",
    needsOnboarding: false,
    isPlatformAdmin: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
  });
}

function renderJoin(token = "tok-abc") {
  return render(
    <MemoryRouter initialEntries={[`/join/${token}`]}>
      <Routes>
        <Route path="/join/:token" element={<JoinLeagueRoute />} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/leagues/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("JoinLeagueRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    mockGetInvitePreview.mockResolvedValue(preview());
    setAuth(true);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("happy path: reads the token param, fetches the preview, renders name + member count", async () => {
    renderJoin("tok-abc");

    expect(await screen.findByText("Friday Mixtape")).toBeInTheDocument();
    expect(screen.getByText(/4 members/i)).toBeInTheDocument();
    expect(mockGetInvitePreview).toHaveBeenCalledWith("tok-abc");
  });

  it("error: getInvitePreview rejecting with 404 renders the notFound state", async () => {
    mockGetInvitePreview.mockRejectedValue(new ApiError(404, "no such invite"));
    renderJoin();

    expect(
      await screen.findByText(/that invite link didn.?t work/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Friday Mixtape")).not.toBeInTheDocument();
  });

  it("expired: getInvitePreview rejecting with 410 renders the expired state", async () => {
    mockGetInvitePreview.mockRejectedValue(new ApiError(410, "gone"));
    renderJoin();

    expect(await screen.findByText(/this link has expired/i)).toBeInTheDocument();
    expect(screen.queryByText("Friday Mixtape")).not.toBeInTheDocument();
  });

  it("authenticated: clicking join calls acceptInvite and navigates to /leagues/{league.id}", async () => {
    setAuth(true);
    mockAcceptInvite.mockResolvedValue(leagueWith("joined-league-7"));
    const user = userEvent.setup();

    renderJoin("tok-abc");
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /join league/i }));

    expect(mockAcceptInvite).toHaveBeenCalledWith("tok-abc");
    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
  });

  it("authenticated: a join failure shows joinError and does not navigate", async () => {
    // Note: an already-member no longer 409s — accept is idempotent (MYS-135).
    // This covers the generic error path (e.g. a server error mid-join).
    setAuth(true);
    mockAcceptInvite.mockRejectedValue(new ApiError(500, "couldn't join the league"));
    const user = userEvent.setup();

    renderJoin();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /join league/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("LEAGUE DETAIL CONTENT")).not.toBeInTheDocument();
  });

  it("authenticated: the join page shows the top nav (MYS-136)", async () => {
    setAuth(true);
    renderJoin("tok-abc");
    await screen.findByText("Friday Mixtape");
    expect(screen.getByRole("navigation")).toBeInTheDocument();
  });

  it("unauthenticated: the join preview has no top nav (MYS-136)", async () => {
    setAuth(false);
    renderJoin("tok-abc");
    await screen.findByText("Friday Mixtape");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("unauthenticated: sign-in stores pendingInvitePath and navigates to /login", async () => {
    setAuth(false);
    const user = userEvent.setup();

    renderJoin("tok-abc");
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(localStorage.getItem("pendingInvitePath")).toBe("/join/tok-abc");
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
    expect(mockAcceptInvite).not.toHaveBeenCalled();
  });
});
