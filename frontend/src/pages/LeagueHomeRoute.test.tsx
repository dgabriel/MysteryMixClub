import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LeagueHomeRoute } from "./LeagueHomeRoute";
import {
  ApiError,
  createInvite,
  getLeague,
  getLeagueMembers,
  removeMember,
  updateLeague,
} from "../services/api";
import type { Invite, League, LeagueMember } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    getLeague: vi.fn(),
    getLeagueMembers: vi.fn(),
    updateLeague: vi.fn(),
    removeMember: vi.fn(),
    createInvite: vi.fn(),
  };
});

// Mock useAuth so we control userId for the isOrganizer branch.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetLeague = vi.mocked(getLeague);
const mockGetLeagueMembers = vi.mocked(getLeagueMembers);
const mockUpdateLeague = vi.mocked(updateLeague);
const mockRemoveMember = vi.mocked(removeMember);
const mockCreateInvite = vi.mocked(createInvite);
const mockUseAuth = vi.mocked(useAuth);

const ORGANIZER_ID = "org-1111";
const MEMBER_ID = "mem-2222";

function leagueWith(overrides: Partial<League> = {}): League {
  return {
    id: "league-1",
    name: "Friday Mixtape",
    description: "the vibe",
    organizer_id: ORGANIZER_ID,
    total_rounds: 6,
    votes_per_player: 3,
    current_round: 2,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function members(): LeagueMember[] {
  return [
    {
      user_id: ORGANIZER_ID,
      display_name: "Ada",
      joined_at: "2026-01-01T00:00:00Z",
      is_organizer: true,
    },
    {
      user_id: MEMBER_ID,
      display_name: "Bo",
      joined_at: "2026-01-02T00:00:00Z",
      is_organizer: false,
    },
  ];
}

function inviteWith(token: string): Invite {
  return {
    id: "invite-1",
    league_id: "league-1",
    token,
    created_by: ORGANIZER_ID,
    created_at: "2026-01-03T00:00:00Z",
    expires_at: null,
  };
}

function setAuth(userId: string | null) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: "Ada",
    userId,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
  });
}

function renderLeague(id = "league-1") {
  return render(
    <MemoryRouter initialEntries={[`/leagues/${id}`]}>
      <Routes>
        <Route path="/leagues/:id" element={<LeagueHomeRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LeagueHomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetLeague.mockResolvedValue(leagueWith());
    mockGetLeagueMembers.mockResolvedValue(members());
    setAuth(ORGANIZER_ID);
  });

  it("happy path: reads the id param, fetches league + members, renders name and members", async () => {
    renderLeague("league-1");

    expect(await screen.findByText("Friday Mixtape")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Bo")).toBeInTheDocument();
    expect(mockGetLeague).toHaveBeenCalledWith("league-1");
    expect(mockGetLeagueMembers).toHaveBeenCalledWith("league-1");
  });

  it("isOrganizer: organizer controls present when userId === organizer_id", async () => {
    setAuth(ORGANIZER_ID);
    renderLeague();

    await screen.findByText("Friday Mixtape");
    // The edit toggle is organizer-only.
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    // Remove is shown on the non-organizer member row.
    expect(screen.getByRole("button", { name: /^remove$/i })).toBeInTheDocument();
  });

  it("not organizer: organizer controls absent when userId !== organizer_id", async () => {
    setAuth(MEMBER_ID);
    renderLeague();

    await screen.findByText("Friday Mixtape");
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^remove$/i })).not.toBeInTheDocument();
  });

  it("error: getLeague rejecting with 403 shows a calm error and does not crash", async () => {
    mockGetLeague.mockRejectedValue(new ApiError(403, "forbidden"));
    renderLeague();

    // The error state renders a back affordance; the screen does not throw.
    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
    expect(screen.queryByText("Friday Mixtape")).not.toBeInTheDocument();
  });

  it("error: getLeague rejecting with 404 shows a calm error and does not crash", async () => {
    mockGetLeague.mockRejectedValue(new ApiError(404, "not found"));
    renderLeague();

    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
  });

  it("invite: generating an invite calls createInvite and shows a /join/{token} url", async () => {
    mockCreateInvite.mockResolvedValue(inviteWith("tok-xyz"));
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^invite$/i }));

    expect(mockCreateInvite).toHaveBeenCalledWith("league-1");
    const field = (await screen.findByLabelText(/share link/i)) as HTMLInputElement;
    expect(field.value).toContain("/join/tok-xyz");
  });

  it("organizer update: submitting the edit form calls updateLeague; a 409 shows updateError", async () => {
    mockUpdateLeague.mockRejectedValue(new ApiError(409, "name taken"));
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed League");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateLeague).toHaveBeenCalledTimes(1);
    expect(mockUpdateLeague).toHaveBeenCalledWith(
      "league-1",
      expect.objectContaining({ name: "Renamed League" }),
    );
    expect(await screen.findByText(/name taken/i)).toBeInTheDocument();
  });

  it("organizer remove: clicking remove on a non-organizer calls removeMember", async () => {
    mockRemoveMember.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(mockRemoveMember).toHaveBeenCalledTimes(1));
    expect(mockRemoveMember).toHaveBeenCalledWith("league-1", MEMBER_ID);
  });

  it("onBack: navigates to /home", async () => {
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^back$/i }));

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });
});
