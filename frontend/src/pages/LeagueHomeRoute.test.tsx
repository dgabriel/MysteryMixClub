import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { LeagueHomeRoute } from "./LeagueHomeRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import {
  ApiError,
  createInvite,
  deleteLeague,
  getLeague,
  getLeagueLeaderboard,
  getLeagueMembers,
  getResults,
  getRounds,
  removeMember,
  updateLeague,
  updateMemberRole,
} from "../services/api";
import type { Invite, League, LeaderboardEntry, LeagueMember, Round, RoundResults } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getLeague: vi.fn(),
    getLeagueLeaderboard: vi.fn(),
    getLeagueMembers: vi.fn(),
    getRounds: vi.fn(),
    getResults: vi.fn(),
    createRound: vi.fn(),
    updateLeague: vi.fn(),
    removeMember: vi.fn(),
    createInvite: vi.fn(),
    deleteLeague: vi.fn(),
    updateMemberRole: vi.fn(),
  };
});

// Mock useAuth so we control userId for the isOrganizer branch.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetLeague = vi.mocked(getLeague);
const mockGetLeagueLeaderboard = vi.mocked(getLeagueLeaderboard);
const mockGetLeagueMembers = vi.mocked(getLeagueMembers);
const mockGetRounds = vi.mocked(getRounds);
const mockGetResults = vi.mocked(getResults);
const mockUpdateLeague = vi.mocked(updateLeague);
const mockRemoveMember = vi.mocked(removeMember);
const mockCreateInvite = vi.mocked(createInvite);
const mockDeleteLeague = vi.mocked(deleteLeague);
const mockUpdateMemberRole = vi.mocked(updateMemberRole);
const mockUseAuth = vi.mocked(useAuth);

const ORGANIZER_ID = "org-1111";
const MEMBER_ID = "mem-2222";
const CO_ORGANIZER_ID = "co-3333";

function leagueWith(overrides: Partial<League> = {}): League {
  return {
    id: "league-1",
    name: "Friday Mixtape",
    description: "the vibe",
    organizer_id: ORGANIZER_ID,
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

function members(): LeagueMember[] {
  return [
    {
      user_id: ORGANIZER_ID,
      display_name: "Ada",
      joined_at: "2026-01-01T00:00:00Z",
      is_organizer: true,
      is_admin: true,
    },
    {
      user_id: MEMBER_ID,
      display_name: "Bo",
      joined_at: "2026-01-02T00:00:00Z",
      is_organizer: false,
      is_admin: false,
    },
  ];
}

// A three-member roster including a promoted co-organizer (MYS-99): the fixed
// organizer, a co-organizer (is_admin true, is_organizer false), and a plain
// member.
function membersWithCoOrganizer(): LeagueMember[] {
  return [
    ...members(),
    {
      user_id: CO_ORGANIZER_ID,
      display_name: "Cy",
      joined_at: "2026-01-03T00:00:00Z",
      is_organizer: false,
      is_admin: true,
    },
  ];
}

function leaderboardFor(memberList: LeagueMember[]): LeaderboardEntry[] {
  return memberList.map((m, i) => ({
    user_id: m.user_id,
    display_name: m.display_name,
    vote_count: 0,
    rank: i + 1,
  }));
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

function closedRound(overrides: Partial<Round> = {}): Round {
  return {
    id: "round-1",
    league_id: "league-1",
    round_number: 1,
    theme: "late summer feels",
    state: "closed",
    description: null,
    submission_deadline: null,
    voting_deadline: null,
    votes_per_player: 3,
    created_at: "2026-01-01T00:00:00Z",
    closed_at: "2026-01-05T00:00:00Z",
    submission_count: 0,
    member_count: 0,
    viewer_submitted: false,
    viewer_voted: false,
    voted_count: 0,
    voting_eligible_count: 0,
    ...overrides,
  };
}

function resultsWith(overrides: Partial<RoundResults> = {}): RoundResults {
  return {
    round_id: "round-1",
    round_number: 1,
    theme: "late summer feels",
    state: "closed",
    viewer_is_vibing: false,
    winners: [],
    picks: [],
    submissions: [],
    leaderboard: [
      { user_id: "u-wren", display_name: "Wren", vote_count: 5, rank: 1 },
      { user_id: "u-cy", display_name: "Cy", vote_count: 2, rank: 2 },
    ],
    most_noted: {
      note_count: 3,
      winners: [
        {
          submission_id: "s-1",
          title: "Strange Currencies",
          artist: "R.E.M.",
          note_count: 3,
          notes: [],
        },
      ],
    },
    ...overrides,
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
    email: "ada@example.com",
    userId,
    isPlatformAdmin: false,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  });
}

function renderLeague(id = "league-1") {
  return render(
    <MemoryRouter initialEntries={[`/leagues/${id}`]}>
      <Routes>
        {/* Mirror production: the route lives under AuthedLayout, which renders
            the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/leagues/:id" element={<LeagueHomeRoute />} />
        </Route>
        <Route path="/home" element={<div>HOME CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LeagueHomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetLeague.mockResolvedValue(leagueWith());
    mockGetLeagueLeaderboard.mockResolvedValue([
      { user_id: ORGANIZER_ID, display_name: "Ada", vote_count: 0, rank: 1 },
      { user_id: MEMBER_ID, display_name: "Bo", vote_count: 0, rank: 2 },
    ] satisfies LeaderboardEntry[]);
    mockGetLeagueMembers.mockResolvedValue(members());
    mockGetRounds.mockResolvedValue([]);
    mockGetResults.mockResolvedValue(resultsWith());
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

  it("invite: generating a shareable link calls createInvite, shows an /invite/{token} url, and notes the 48h expiry", async () => {
    mockCreateInvite.mockResolvedValue(inviteWith("tok-xyz"));
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^invite$/i }));

    expect(mockCreateInvite).toHaveBeenCalledWith("league-1");
    const field = (await screen.findByLabelText(/share link/i)) as HTMLInputElement;
    expect(field.value).toContain("/invite/tok-xyz");
    expect(screen.getByText(/expires in 48 hours/i)).toBeInTheDocument();
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

  // --- Deadline windows (MYS-160). The submission/voting window fields share
  // the "days"/"hours" labels between the two DeadlineWindowFields, so we look
  // them up by id rather than label text. ---

  it("deadline windows: opening the edit form pre-fills submission/voting windows from the league's current hours", async () => {
    mockGetLeague.mockResolvedValue(
      leagueWith({ submission_window_hours: 102, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    expect((container.querySelector("#edit-submission-window-days") as HTMLInputElement).value).toBe(
      "4",
    );
    expect(
      (container.querySelector("#edit-submission-window-hours") as HTMLInputElement).value,
    ).toBe("6");
    expect((container.querySelector("#edit-voting-window-days") as HTMLInputElement).value).toBe(
      "3",
    );
    expect((container.querySelector("#edit-voting-window-hours") as HTMLInputElement).value).toBe(
      "0",
    );
  });

  it("deadline windows: changing one window and saving includes only the changed window's hours (diff-based)", async () => {
    mockGetLeague.mockResolvedValue(
      leagueWith({ submission_window_hours: 72, voting_window_hours: 72 }),
    );
    mockUpdateLeague.mockResolvedValue(
      leagueWith({ submission_window_hours: 96, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    fireEvent.change(container.querySelector("#edit-submission-window-days") as HTMLInputElement, {
      target: { value: "4" },
    });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateLeague).toHaveBeenCalledTimes(1);
    const [, input] = mockUpdateLeague.mock.calls[0];
    expect(input).toMatchObject({ submission_window_hours: 96 });
    expect(input).not.toHaveProperty("voting_window_hours");
  });

  it("deadline windows: an out-of-range window blocks the entire save (name change withheld too) and shows windowError", async () => {
    mockGetLeague.mockResolvedValue(
      leagueWith({ submission_window_hours: 72, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed League");
    fireEvent.change(container.querySelector("#edit-submission-window-days") as HTMLInputElement, {
      target: { value: "0" },
    });
    fireEvent.change(container.querySelector("#edit-submission-window-hours") as HTMLInputElement, {
      target: { value: "2" },
    });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/submission windows need at least 4 hours\./i)).toBeInTheDocument();
    expect(mockUpdateLeague).not.toHaveBeenCalled();
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

  // --- Co-organizer promote/demote (MYS-99) ---

  it("co-organizer badge: renders for a member with is_admin && !is_organizer, not for the fixed organizer or a plain member", async () => {
    const roster = membersWithCoOrganizer();
    mockGetLeagueMembers.mockResolvedValue(roster);
    mockGetLeagueLeaderboard.mockResolvedValue(leaderboardFor(roster));

    renderLeague();
    await screen.findByText("Friday Mixtape");

    expect(await screen.findByText("co-organizer")).toBeInTheDocument();
    // Exactly one co-organizer badge — the fixed organizer gets "organizer"
    // instead, and the plain member gets neither.
    expect(screen.getAllByText("co-organizer")).toHaveLength(1);
    expect(screen.getByText("organizer")).toBeInTheDocument();
  });

  it("make admin: appears for an admin viewer on a plain member, calls updateMemberRole with role admin, shows a busy state, and surfaces an error on failure", async () => {
    mockUpdateMemberRole.mockRejectedValue(new ApiError(500, "couldn't update that member's role"));
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    const makeAdminBtn = screen.getByRole("button", { name: /^make admin$/i });
    await user.click(makeAdminBtn);

    expect(mockUpdateMemberRole).toHaveBeenCalledWith("league-1", MEMBER_ID, "admin");
    expect(
      await screen.findByText(/couldn't update that member's role/i),
    ).toBeInTheDocument();
  });

  it("make admin: shows a busy 'saving…' state while the request is in flight", async () => {
    let resolvePromise!: (value: LeagueMember) => void;
    mockUpdateMemberRole.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
    );
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^make admin$/i }));

    expect(await screen.findByRole("button", { name: /^saving…$/i })).toBeInTheDocument();

    resolvePromise({
      user_id: MEMBER_ID,
      display_name: "Bo",
      joined_at: "2026-01-02T00:00:00Z",
      is_organizer: false,
      is_admin: true,
    });

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^saving…$/i })).not.toBeInTheDocument(),
    );
  });

  it("remove admin: appears for an admin viewer on a co-organizer (not the fixed organizer), calls updateMemberRole with role member", async () => {
    const roster = membersWithCoOrganizer();
    mockGetLeagueMembers.mockResolvedValue(roster);
    mockGetLeagueLeaderboard.mockResolvedValue(leaderboardFor(roster));
    mockUpdateMemberRole.mockResolvedValue({
      user_id: CO_ORGANIZER_ID,
      display_name: "Cy",
      joined_at: "2026-01-03T00:00:00Z",
      is_organizer: false,
      is_admin: false,
    });
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    // The fixed organizer's row never shows a role toggle; only the
    // co-organizer's row does, alongside the plain member's "make admin".
    const removeAdminBtn = screen.getByRole("button", { name: /^remove admin$/i });
    await user.click(removeAdminBtn);

    expect(mockUpdateMemberRole).toHaveBeenCalledWith("league-1", CO_ORGANIZER_ID, "member");
  });

  describe("co-organizer viewer parity", () => {
    beforeEach(() => {
      const roster = membersWithCoOrganizer();
      mockGetLeagueMembers.mockResolvedValue(roster);
      mockGetLeagueLeaderboard.mockResolvedValue(leaderboardFor(roster));
      setAuth(CO_ORGANIZER_ID);
    });

    it("a co-organizer viewer (isAdmin, not isOrganizer) sees league-edit and member-removal controls a plain member does not", async () => {
      renderLeague();
      await screen.findByText("Friday Mixtape");

      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
      // Remove is available on both the plain member's row and the other
      // co-organizer's row (never the fixed organizer's), per showRoleAndRemove.
      expect(screen.getAllByRole("button", { name: /^remove$/i })).toHaveLength(2);
    });

    it("a co-organizer viewer sees BOTH the delete-league and leave-league sections", async () => {
      renderLeague();
      await screen.findByText("Friday Mixtape");

      expect(screen.getByRole("button", { name: /^delete league$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^leave league$/i })).toBeInTheDocument();
    });
  });

  it("the fixed organizer sees only the delete-league section, not leave-league", async () => {
    renderLeague();
    await screen.findByText("Friday Mixtape");

    expect(screen.getByRole("button", { name: /^delete league$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^leave league$/i })).not.toBeInTheDocument();
  });

  it("a plain member sees only the leave-league section, not delete-league", async () => {
    setAuth(MEMBER_ID);
    renderLeague();
    await screen.findByText("Friday Mixtape");

    expect(screen.queryByRole("button", { name: /^delete league$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^leave league$/i })).toBeInTheDocument();
  });

  it("nav: the TopNav home link navigates to /home", async () => {
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    // Two "home" controls in the TopNav (ring mark + text link); either routes home.
    await user.click(screen.getAllByRole("button", { name: /^home$/i })[1]);

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("open_submission round: shows submission progress (X of Y submitted) on the card — MYS-101", async () => {
    mockGetRounds.mockResolvedValue([
      closedRound({
        id: "round-open",
        state: "open_submission",
        closed_at: null,
        submission_count: 3,
        member_count: 6,
      }),
    ]);

    renderLeague();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText("3 of 6 submitted")).toBeInTheDocument();
  });

  it("active round: shows the static deadline line on the card — MYS-161", async () => {
    // An open round with a deadline shows "closes …" (lowercase DOM; uppercase CSS).
    mockGetRounds.mockResolvedValue([
      closedRound({
        id: "round-open",
        state: "open_submission",
        closed_at: null,
        submission_count: 1,
        member_count: 6,
        submission_deadline: "2026-07-05T12:00:00Z",
      }),
    ]);

    renderLeague();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText(/^closes /i)).toBeInTheDocument();
  });

  it("closed round: shows the single winner and most-noted pick on the card", async () => {
    mockGetRounds.mockResolvedValue([closedRound()]);
    mockGetResults.mockResolvedValue(resultsWith());

    renderLeague();
    await screen.findByText("Friday Mixtape");

    expect(await screen.findByText("winner")).toBeInTheDocument();
    expect(screen.getByText("Wren")).toBeInTheDocument();
    expect(screen.getByText("most noted")).toBeInTheDocument();
    expect(screen.getByText("Strange Currencies")).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledWith("round-1");
  });

  it("closed round tie: shows every co-winner and every most-noted pick", async () => {
    mockGetRounds.mockResolvedValue([closedRound()]);
    mockGetResults.mockResolvedValue(
      resultsWith({
        leaderboard: [
          { user_id: "u-ada", display_name: "Ada", vote_count: 4, rank: 1 },
          { user_id: "u-bo", display_name: "Bo", vote_count: 4, rank: 2 },
          { user_id: "u-cy", display_name: "Cy", vote_count: 1, rank: 3 },
        ],
        most_noted: {
          note_count: 2,
          winners: [
            {
              submission_id: "s-1",
              title: "Strange Currencies",
              artist: "R.E.M.",
              note_count: 2,
              notes: [],
            },
            {
              submission_id: "s-2",
              title: "Nightswimming",
              artist: "R.E.M.",
              note_count: 2,
              notes: [],
            },
          ],
        },
      }),
    );

    renderLeague();
    await screen.findByText("Friday Mixtape");

    expect(await screen.findByText("winners")).toBeInTheDocument();
    expect(screen.getByText("Ada & Bo")).toBeInTheDocument();
    // Cy did not tie for first and is not named as a winner.
    expect(screen.queryByText(/Cy/)).not.toBeInTheDocument();
    expect(screen.getByText("Strange Currencies · Nightswimming")).toBeInTheDocument();
  });

  it("closed round with no votes or notes: omits the summary entirely", async () => {
    mockGetRounds.mockResolvedValue([closedRound()]);
    mockGetResults.mockResolvedValue(
      resultsWith({
        leaderboard: [{ user_id: "u-ada", display_name: "Ada", vote_count: 0, rank: 1 }],
        most_noted: { note_count: 0, winners: [] },
      }),
    );

    renderLeague();
    // The round card still renders…
    expect(await screen.findByText("late summer feels")).toBeInTheDocument();
    // …but with no winner / most-noted summary.
    await waitFor(() => expect(mockGetResults).toHaveBeenCalled());
    expect(screen.queryByText("winner")).not.toBeInTheDocument();
    expect(screen.queryByText("most noted")).not.toBeInTheDocument();
  });

  // --- Organizer admin: delete league (MYS-124) ---

  it("delete league: confirm step calls deleteLeague and navigates to /home", async () => {
    mockDeleteLeague.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    // First click arms the confirm; the destructive action only fires on the second.
    await user.click(screen.getByRole("button", { name: /^delete league$/i }));
    await user.click(screen.getByRole("button", { name: /^delete this league$/i }));

    await waitFor(() => expect(mockDeleteLeague).toHaveBeenCalledWith("league-1"));
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("delete league: a failure shows a calm error and does not navigate", async () => {
    // Delete is allowed in any state now (MYS-137); this covers the generic
    // error path (e.g. a server error), which still keeps the user in place.
    mockDeleteLeague.mockRejectedValue(new ApiError(500, "couldn't delete the league"));
    const user = userEvent.setup();

    renderLeague();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^delete league$/i }));
    await user.click(screen.getByRole("button", { name: /^delete this league$/i }));

    expect(await screen.findByText(/couldn't delete the league/i)).toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
  });

  it("open_voting round: shows voting progress (X of Y voted) on the card — MYS-110", async () => {
    mockGetRounds.mockResolvedValue([
      closedRound({
        id: "round-voting",
        state: "open_voting",
        closed_at: null,
        voted_count: 2,
        voting_eligible_count: 5,
      }),
    ]);

    renderLeague();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText("2 of 5 voted")).toBeInTheDocument();
  });

  it("open_voting round: hides voting progress when eligible count is zero — MYS-110", async () => {
    mockGetRounds.mockResolvedValue([
      closedRound({
        id: "round-voting-empty",
        state: "open_voting",
        closed_at: null,
        voted_count: 0,
        voting_eligible_count: 0,
      }),
    ]);

    renderLeague();
    await screen.findByText("Friday Mixtape");
    expect(screen.queryByText(/of 0 voted/i)).not.toBeInTheDocument();
  });
});
