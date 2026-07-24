import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ClubHomeRoute } from "./ClubHomeRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import {
  ApiError,
  createInvite,
  deleteClub,
  getClub,
  getClubLeaderboard,
  getClubMembers,
  getResults,
  getMixes,
  removeMember,
  updateClub,
  updateMemberRole,
} from "../services/api";
import type { Invite, Club, LeaderboardEntry, ClubMember, Mix, MixResults } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getClub: vi.fn(),
    getClubLeaderboard: vi.fn(),
    getClubMembers: vi.fn(),
    getMixes: vi.fn(),
    getResults: vi.fn(),
    createMix: vi.fn(),
    updateClub: vi.fn(),
    removeMember: vi.fn(),
    createInvite: vi.fn(),
    deleteClub: vi.fn(),
    updateMemberRole: vi.fn(),
  };
});

// Mock useAuth so we control userId for the isOrganizer branch.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetClub = vi.mocked(getClub);
const mockGetClubLeaderboard = vi.mocked(getClubLeaderboard);
const mockGetClubMembers = vi.mocked(getClubMembers);
const mockGetMixes = vi.mocked(getMixes);
const mockGetResults = vi.mocked(getResults);
const mockUpdateClub = vi.mocked(updateClub);
const mockRemoveMember = vi.mocked(removeMember);
const mockCreateInvite = vi.mocked(createInvite);
const mockDeleteClub = vi.mocked(deleteClub);
const mockUpdateMemberRole = vi.mocked(updateMemberRole);
const mockUseAuth = vi.mocked(useAuth);

const ORGANIZER_ID = "org-1111";
const MEMBER_ID = "mem-2222";
const CO_ORGANIZER_ID = "co-3333";

function clubWith(overrides: Partial<Club> = {}): Club {
  return {
    id: "club-1",
    name: "Friday Mixtape",
    description: "the vibe",
    organizer_id: ORGANIZER_ID,
    total_mixes: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_mix: 2,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    completed_at: null,
    ...overrides,
  };
}

function members(): ClubMember[] {
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
function membersWithCoOrganizer(): ClubMember[] {
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

function leaderboardFor(memberList: ClubMember[]): LeaderboardEntry[] {
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
    club_id: "club-1",
    token,
    created_by: ORGANIZER_ID,
    created_at: "2026-01-03T00:00:00Z",
    expires_at: null,
  };
}

function closedMix(overrides: Partial<Mix> = {}): Mix {
  return {
    id: "mix-1",
    club_id: "club-1",
    mix_number: 1,
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

function resultsWith(overrides: Partial<MixResults> = {}): MixResults {
  return {
    mix_id: "mix-1",
    mix_number: 1,
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

function renderClub(id = "club-1") {
  return render(
    <MemoryRouter initialEntries={[`/clubs/${id}`]}>
      <Routes>
        {/* Mirror production: the route lives under AuthedLayout, which renders
            the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/clubs/:id" element={<ClubHomeRoute />} />
        </Route>
        <Route path="/home" element={<div>HOME CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ClubHomeRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetClub.mockResolvedValue(clubWith());
    mockGetClubLeaderboard.mockResolvedValue([
      { user_id: ORGANIZER_ID, display_name: "Ada", vote_count: 0, rank: 1 },
      { user_id: MEMBER_ID, display_name: "Bo", vote_count: 0, rank: 2 },
    ] satisfies LeaderboardEntry[]);
    mockGetClubMembers.mockResolvedValue(members());
    mockGetMixes.mockResolvedValue([]);
    mockGetResults.mockResolvedValue(resultsWith());
    setAuth(ORGANIZER_ID);
  });

  it("happy path: reads the id param, fetches club + members, renders name and members", async () => {
    renderClub("club-1");

    expect(await screen.findByText("Friday Mixtape")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Bo")).toBeInTheDocument();
    expect(mockGetClub).toHaveBeenCalledWith("club-1");
    expect(mockGetClubMembers).toHaveBeenCalledWith("club-1");
  });

  it("isOrganizer: organizer controls present when userId === organizer_id", async () => {
    setAuth(ORGANIZER_ID);
    renderClub();

    await screen.findByText("Friday Mixtape");
    // The edit toggle is organizer-only.
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    // Remove is shown on the non-organizer member row.
    expect(screen.getByRole("button", { name: /^remove$/i })).toBeInTheDocument();
  });

  it("not organizer: organizer controls absent when userId !== organizer_id", async () => {
    setAuth(MEMBER_ID);
    renderClub();

    await screen.findByText("Friday Mixtape");
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^remove$/i })).not.toBeInTheDocument();
  });

  it("MYS-246: a plain (non-admin) member never sees the invite section", async () => {
    setAuth(MEMBER_ID);
    renderClub();

    await screen.findByText("Friday Mixtape");
    expect(screen.queryByRole("heading", { name: /^invite$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^invite$/i })).not.toBeInTheDocument();
  });

  it("error: getClub rejecting with 403 shows a calm error and does not crash", async () => {
    mockGetClub.mockRejectedValue(new ApiError(403, "forbidden"));
    renderClub();

    // The error state renders a back affordance; the screen does not throw.
    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
    expect(screen.queryByText("Friday Mixtape")).not.toBeInTheDocument();
  });

  it("error: getClub rejecting with 404 shows a calm error and does not crash", async () => {
    mockGetClub.mockRejectedValue(new ApiError(404, "not found"));
    renderClub();

    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
  });

  it("invite: generating a shareable link calls createInvite, shows an /invite/{token} url, and notes the 48h expiry", async () => {
    mockCreateInvite.mockResolvedValue(inviteWith("tok-xyz"));
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^invite$/i }));

    expect(mockCreateInvite).toHaveBeenCalledWith("club-1");
    const field = (await screen.findByLabelText(/share link/i)) as HTMLInputElement;
    expect(field.value).toContain("/invite/tok-xyz");
    expect(screen.getByText(/expires in 48 hours/i)).toBeInTheDocument();
  });

  it("organizer update: submitting the edit form calls updateClub; a 409 shows updateError", async () => {
    mockUpdateClub.mockRejectedValue(new ApiError(409, "name taken"));
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Club");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateClub).toHaveBeenCalledTimes(1);
    expect(mockUpdateClub).toHaveBeenCalledWith(
      "club-1",
      expect.objectContaining({ name: "Renamed Club" }),
    );
    expect(await screen.findByText(/name taken/i)).toBeInTheDocument();
  });

  // --- Deadline windows (MYS-160). The submission/voting window fields share
  // the "days"/"hours" labels between the two DeadlineWindowFields, so we look
  // them up by id rather than label text. ---

  it("deadline windows: opening the edit form pre-fills submission/voting windows from the club's current hours", async () => {
    mockGetClub.mockResolvedValue(
      clubWith({ submission_window_hours: 102, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderClub();
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
    mockGetClub.mockResolvedValue(
      clubWith({ submission_window_hours: 72, voting_window_hours: 72 }),
    );
    mockUpdateClub.mockResolvedValue(
      clubWith({ submission_window_hours: 96, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    fireEvent.change(container.querySelector("#edit-submission-window-days") as HTMLInputElement, {
      target: { value: "4" },
    });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockUpdateClub).toHaveBeenCalledTimes(1);
    const [, input] = mockUpdateClub.mock.calls[0];
    expect(input).toMatchObject({ submission_window_hours: 96 });
    expect(input).not.toHaveProperty("voting_window_hours");
  });

  it("deadline windows: an out-of-range window blocks the entire save (name change withheld too) and shows windowError", async () => {
    mockGetClub.mockResolvedValue(
      clubWith({ submission_window_hours: 72, voting_window_hours: 72 }),
    );
    const user = userEvent.setup();

    const { container } = renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const nameInput = screen.getByLabelText(/^name$/i);
    await user.clear(nameInput);
    await user.type(nameInput, "Renamed Club");
    fireEvent.change(container.querySelector("#edit-submission-window-days") as HTMLInputElement, {
      target: { value: "0" },
    });
    fireEvent.change(container.querySelector("#edit-submission-window-hours") as HTMLInputElement, {
      target: { value: "2" },
    });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/submission windows need at least 4 hours\./i)).toBeInTheDocument();
    expect(mockUpdateClub).not.toHaveBeenCalled();
  });

  it("organizer remove: clicking remove on a non-organizer calls removeMember", async () => {
    mockRemoveMember.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(mockRemoveMember).toHaveBeenCalledTimes(1));
    expect(mockRemoveMember).toHaveBeenCalledWith("club-1", MEMBER_ID);
  });

  // --- Co-organizer promote/demote (MYS-99) ---

  it("co-organizer badge: renders for a member with is_admin && !is_organizer, not for the fixed organizer or a plain member", async () => {
    const roster = membersWithCoOrganizer();
    mockGetClubMembers.mockResolvedValue(roster);
    mockGetClubLeaderboard.mockResolvedValue(leaderboardFor(roster));

    renderClub();
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

    renderClub();
    await screen.findByText("Friday Mixtape");

    const makeAdminBtn = screen.getByRole("button", { name: /^make admin$/i });
    await user.click(makeAdminBtn);

    expect(mockUpdateMemberRole).toHaveBeenCalledWith("club-1", MEMBER_ID, "admin");
    expect(
      await screen.findByText(/couldn't update that member's role/i),
    ).toBeInTheDocument();
  });

  it("make admin: shows a busy 'saving…' state while the request is in flight", async () => {
    let resolvePromise!: (value: ClubMember) => void;
    mockUpdateMemberRole.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePromise = resolve;
        }),
    );
    const user = userEvent.setup();

    renderClub();
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
    mockGetClubMembers.mockResolvedValue(roster);
    mockGetClubLeaderboard.mockResolvedValue(leaderboardFor(roster));
    mockUpdateMemberRole.mockResolvedValue({
      user_id: CO_ORGANIZER_ID,
      display_name: "Cy",
      joined_at: "2026-01-03T00:00:00Z",
      is_organizer: false,
      is_admin: false,
    });
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    // The fixed organizer's row never shows a role toggle; only the
    // co-organizer's row does, alongside the plain member's "make admin".
    const removeAdminBtn = screen.getByRole("button", { name: /^remove admin$/i });
    await user.click(removeAdminBtn);

    expect(mockUpdateMemberRole).toHaveBeenCalledWith("club-1", CO_ORGANIZER_ID, "member");
  });

  describe("co-organizer viewer parity", () => {
    beforeEach(() => {
      const roster = membersWithCoOrganizer();
      mockGetClubMembers.mockResolvedValue(roster);
      mockGetClubLeaderboard.mockResolvedValue(leaderboardFor(roster));
      setAuth(CO_ORGANIZER_ID);
    });

    it("a co-organizer viewer (isAdmin, not isOrganizer) sees club-edit and member-removal controls a plain member does not", async () => {
      renderClub();
      await screen.findByText("Friday Mixtape");

      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
      // Remove is available on both the plain member's row and the other
      // co-organizer's row (never the fixed organizer's), per showRoleAndRemove.
      expect(screen.getAllByRole("button", { name: /^remove$/i })).toHaveLength(2);
    });

    it("a co-organizer viewer sees BOTH the delete-club and leave-club sections", async () => {
      renderClub();
      await screen.findByText("Friday Mixtape");

      expect(screen.getByRole("button", { name: /^delete club$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^leave club$/i })).toBeInTheDocument();
    });

    it("MYS-246: a co-organizer viewer sees the invite section", async () => {
      renderClub();
      await screen.findByText("Friday Mixtape");

      expect(screen.getByRole("heading", { name: /^invite$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^invite$/i })).toBeInTheDocument();
    });
  });

  it("the fixed organizer sees only the delete-club section, not leave-club", async () => {
    renderClub();
    await screen.findByText("Friday Mixtape");

    expect(screen.getByRole("button", { name: /^delete club$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^leave club$/i })).not.toBeInTheDocument();
  });

  it("a plain member sees only the leave-club section, not delete-club", async () => {
    setAuth(MEMBER_ID);
    renderClub();
    await screen.findByText("Friday Mixtape");

    expect(screen.queryByRole("button", { name: /^delete club$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^leave club$/i })).toBeInTheDocument();
  });

  it("nav: the TopNav home link navigates to /home", async () => {
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    // Two "home" controls in the TopNav (ring mark + text link); either routes home.
    await user.click(screen.getAllByRole("button", { name: /^home$/i })[1]);

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("open_submission mix: shows submission progress (X of Y submitted) on the card — MYS-101", async () => {
    mockGetMixes.mockResolvedValue([
      closedMix({
        id: "mix-open",
        state: "open_submission",
        closed_at: null,
        submission_count: 3,
        member_count: 6,
      }),
    ]);

    renderClub();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText("3 of 6 submitted")).toBeInTheDocument();
  });

  it("active mix: shows the static deadline line on the card — MYS-161", async () => {
    // An open mix with a deadline shows "closes …" (lowercase DOM; uppercase CSS).
    mockGetMixes.mockResolvedValue([
      closedMix({
        id: "mix-open",
        state: "open_submission",
        closed_at: null,
        submission_count: 1,
        member_count: 6,
        submission_deadline: "2026-07-05T12:00:00Z",
      }),
    ]);

    renderClub();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText(/^closes /i)).toBeInTheDocument();
  });

  it("closed mix: shows the single winner and most-noted pick on the card", async () => {
    mockGetMixes.mockResolvedValue([closedMix()]);
    mockGetResults.mockResolvedValue(resultsWith());

    renderClub();
    await screen.findByText("Friday Mixtape");

    expect(await screen.findByText("winner")).toBeInTheDocument();
    expect(screen.getByText("Wren")).toBeInTheDocument();
    expect(screen.getByText("most noted")).toBeInTheDocument();
    expect(screen.getByText("Strange Currencies")).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledWith("mix-1");
  });

  it("closed mix tie: shows every co-winner and every most-noted pick", async () => {
    mockGetMixes.mockResolvedValue([closedMix()]);
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

    renderClub();
    await screen.findByText("Friday Mixtape");

    expect(await screen.findByText("winners")).toBeInTheDocument();
    expect(screen.getByText("Ada & Bo")).toBeInTheDocument();
    // Cy did not tie for first and is not named as a winner.
    expect(screen.queryByText(/Cy/)).not.toBeInTheDocument();
    expect(screen.getByText("Strange Currencies · Nightswimming")).toBeInTheDocument();
  });

  it("closed mix with no votes or notes: omits the summary entirely", async () => {
    mockGetMixes.mockResolvedValue([closedMix()]);
    mockGetResults.mockResolvedValue(
      resultsWith({
        leaderboard: [{ user_id: "u-ada", display_name: "Ada", vote_count: 0, rank: 1 }],
        most_noted: { note_count: 0, winners: [] },
      }),
    );

    renderClub();
    // The mix card still renders…
    expect(await screen.findByText("late summer feels")).toBeInTheDocument();
    // …but with no winner / most-noted summary.
    await waitFor(() => expect(mockGetResults).toHaveBeenCalled());
    expect(screen.queryByText("winner")).not.toBeInTheDocument();
    expect(screen.queryByText("most noted")).not.toBeInTheDocument();
  });

  // --- Organizer admin: delete club (MYS-124) ---

  it("delete club: confirm step calls deleteClub and navigates to /home", async () => {
    mockDeleteClub.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    // First click arms the confirm; the destructive action only fires on the second.
    await user.click(screen.getByRole("button", { name: /^delete club$/i }));
    await user.click(screen.getByRole("button", { name: /^delete this club$/i }));

    await waitFor(() => expect(mockDeleteClub).toHaveBeenCalledWith("club-1"));
    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
  });

  it("delete club: a failure shows a calm error and does not navigate", async () => {
    // Delete is allowed in any state now (MYS-137); this covers the generic
    // error path (e.g. a server error), which still keeps the user in place.
    mockDeleteClub.mockRejectedValue(new ApiError(500, "couldn't delete the club"));
    const user = userEvent.setup();

    renderClub();
    await screen.findByText("Friday Mixtape");

    await user.click(screen.getByRole("button", { name: /^delete club$/i }));
    await user.click(screen.getByRole("button", { name: /^delete this club$/i }));

    expect(await screen.findByText(/couldn't delete the club/i)).toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
  });

  it("open_voting mix: shows voting progress (X of Y voted) on the card — MYS-110", async () => {
    mockGetMixes.mockResolvedValue([
      closedMix({
        id: "mix-voting",
        state: "open_voting",
        closed_at: null,
        voted_count: 2,
        voting_eligible_count: 5,
      }),
    ]);

    renderClub();
    await screen.findByText("Friday Mixtape");
    expect(await screen.findByText("2 of 5 voted")).toBeInTheDocument();
  });

  it("open_voting mix: hides voting progress when eligible count is zero — MYS-110", async () => {
    mockGetMixes.mockResolvedValue([
      closedMix({
        id: "mix-voting-empty",
        state: "open_voting",
        closed_at: null,
        voted_count: 0,
        voting_eligible_count: 0,
      }),
    ]);

    renderClub();
    await screen.findByText("Friday Mixtape");
    expect(screen.queryByText(/of 0 voted/i)).not.toBeInTheDocument();
  });
});
