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

function preview(overrides: Partial<InvitePreview> = {}): InvitePreview {
  return {
    league_id: "league-preview-1",
    league_name: "Friday Mixtape",
    member_count: 4,
    already_member: false,
    ...overrides,
  };
}

function platformPreview(overrides: Partial<InvitePreview> = {}): InvitePreview {
  return {
    league_id: null,
    league_name: null,
    member_count: null,
    already_member: false,
    ...overrides,
  };
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
    submission_window_hours: 72,
    voting_window_hours: 72,
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
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
}

function joinTree(token: string) {
  return (
    <MemoryRouter initialEntries={[`/join/${token}`]}>
      <Routes>
        <Route path="/join/:token" element={<JoinLeagueRoute />} />
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/leagues/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>
  );
}

function renderJoin(token = "tok-abc") {
  return render(joinTree(token));
}

function loadingAuth() {
  mockUseAuth.mockReturnValue({
    status: "loading",
    isAuthenticated: false,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: null,
    email: null,
    userId: null,
    profileStatus: "idle",
    needsOnboarding: false,
    isPlatformAdmin: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
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

  describe("waits for auth status to resolve (MYS-181 fix)", () => {
    it("does not fetch the preview while status is still 'loading', to avoid misreading an authenticated visitor as anonymous", async () => {
      loadingAuth();
      const { rerender } = renderJoin("tok-abc");

      // Auth is still resolving (the on-mount silent refresh hasn't completed)
      // — fetching now would race it and read as anonymous.
      expect(mockGetInvitePreview).not.toHaveBeenCalled();

      setAuth(true);
      rerender(joinTree("tok-abc"));

      expect(await screen.findByText("Friday Mixtape")).toBeInTheDocument();
      expect(mockGetInvitePreview).toHaveBeenCalledWith("tok-abc");
    });
  });

  describe("already a member (MYS-181)", () => {
    it("preview with already_member true redirects straight into the league, skipping the join screen", async () => {
      mockGetInvitePreview.mockResolvedValue(
        preview({ league_id: "league-99", already_member: true }),
      );

      renderJoin("tok-abc");

      expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
      expect(screen.queryByText("Friday Mixtape")).not.toBeInTheDocument();
      expect(mockAcceptInvite).not.toHaveBeenCalled();
    });
  });

  describe("platform invite (MYS-182)", () => {
    it("authenticated: redirects straight to /home, skipping the join screen", async () => {
      setAuth(true);
      mockGetInvitePreview.mockResolvedValue(platformPreview());

      renderJoin("tok-abc");

      expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
      expect(mockAcceptInvite).not.toHaveBeenCalled();
    });

    it("unauthenticated: shows generic copy and a sign-in button, no league name or member count", async () => {
      setAuth(false);
      mockGetInvitePreview.mockResolvedValue(platformPreview());

      renderJoin("tok-abc");

      expect(await screen.findByText(/you're invited to mysterymixclub/i)).toBeInTheDocument();
      expect(screen.getByText(/sign in to get started/i)).toBeInTheDocument();
      expect(screen.queryByText(/members/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /join league/i })).not.toBeInTheDocument();
    });

    it("unauthenticated: sign-in stores pendingInvitePath and navigates to /login, same as a league invite", async () => {
      setAuth(false);
      mockGetInvitePreview.mockResolvedValue(platformPreview());
      const user = userEvent.setup();

      renderJoin("tok-abc");
      await screen.findByText(/you're invited to mysterymixclub/i);

      await user.click(screen.getByRole("button", { name: /sign in/i }));

      expect(localStorage.getItem("pendingInvitePath")).toBe("/join/tok-abc");
      expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
    });
  });

  describe("expired link CTA (MYS-181)", () => {
    it("signed in: shows a 'go home' button that navigates to /home", async () => {
      setAuth(true);
      mockGetInvitePreview.mockRejectedValue(new ApiError(410, "gone"));
      const user = userEvent.setup();

      renderJoin("tok-abc");
      await screen.findByText(/this link has expired/i);

      await user.click(screen.getByRole("button", { name: /go home/i }));
      expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
    });

    it("signed out: shows a 'sign in' button that navigates to /login without stashing a pending invite", async () => {
      setAuth(false);
      mockGetInvitePreview.mockRejectedValue(new ApiError(410, "gone"));
      const user = userEvent.setup();

      renderJoin("tok-abc");
      await screen.findByText(/this link has expired/i);

      await user.click(screen.getByRole("button", { name: /sign in/i }));

      expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
      // The link is dead either way — nothing worth stashing to return to.
      expect(localStorage.getItem("pendingInvitePath")).toBeNull();
    });
  });
});
