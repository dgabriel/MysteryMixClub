import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { ClubHomeRoute } from "./ClubHomeRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import {
  ApiError,
  blockUser,
  createInvite,
  deleteClub,
  getClub,
  getClubLeaderboard,
  getClubMembers,
  getResults,
  getMixes,
  removeMember,
  unblockUser,
  updateClub,
  updateMemberRole,
  updateMix,
} from "../services/api";
import type { Invite, Club, LeaderboardEntry, ClubMember, Mix, MixResults } from "../services/api";
import { useAuth } from "../hooks/useAuth";
import { dismissGuide, isGuideDismissed, markJustJoinedClub } from "../data/onboardingGuides";
import { markLatestReleaseSeen } from "../data/releaseNotes";

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
    updateMix: vi.fn(),
    removeMember: vi.fn(),
    createInvite: vi.fn(),
    deleteClub: vi.fn(),
    updateMemberRole: vi.fn(),
    blockUser: vi.fn(),
    unblockUser: vi.fn(),
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
const mockUpdateMix = vi.mocked(updateMix);
const mockRemoveMember = vi.mocked(removeMember);
const mockCreateInvite = vi.mocked(createInvite);
const mockDeleteClub = vi.mocked(deleteClub);
const mockUpdateMemberRole = vi.mocked(updateMemberRole);
const mockBlockUser = vi.mocked(blockUser);
const mockUnblockUser = vi.mocked(unblockUser);
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
    deadline_mode: "duration",
    timezone: "UTC",
    submission_weekday: null,
    submission_time: null,
    voting_weekday: null,
    voting_time: null,
    completed_at: null,
    viewer_is_admin: null,
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
    missing_submitters: null,
    missing_voters: null,
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
        <Route path="/clubs/:id/songs" element={<div>CLUB SONGS CONTENT</div>} />
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
    mockBlockUser.mockResolvedValue({
      user_id: MEMBER_ID,
      display_name: "Bo",
      created_at: "2026-01-03T00:00:00Z",
    });
    mockUnblockUser.mockResolvedValue(undefined);
    setAuth(ORGANIZER_ID);
  });

  it("happy path: reads the id param, fetches club + members, renders name and members", async () => {
    renderClub("club-1");

    expect(await screen.findByRole("heading", { name: "Friday Mixtape" })).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.getByText("Bo")).toBeInTheDocument();
    expect(mockGetClub).toHaveBeenCalledWith("club-1");
    expect(mockGetClubMembers).toHaveBeenCalledWith("club-1");
  });

  it("navigates to the club's song list", async () => {
    renderClub("club-1");
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    await userEvent.click(screen.getByRole("button", { name: /view all songs/i }));

    expect(await screen.findByText("CLUB SONGS CONTENT")).toBeInTheDocument();
  });

  it("mix order: active first, then upcoming by number, then closed by number", async () => {
    // Deliberately handed to the screen in the API's own plain mix-number
    // order, which is what buries the only actionable row in the middle.
    mockGetMixes.mockResolvedValue([
      closedMix({ id: "m1", mix_number: 1, theme: "One", state: "closed" }),
      closedMix({ id: "m2", mix_number: 2, theme: "Two", state: "closed" }),
      closedMix({ id: "m3", mix_number: 3, theme: "Three", state: "open_voting" }),
      closedMix({ id: "m4", mix_number: 4, theme: "Four", state: "pending" }),
      closedMix({ id: "m5", mix_number: 5, theme: "Five", state: "pending" }),
    ]);
    renderClub();

    await screen.findByRole("heading", { name: "Friday Mixtape" });

    // The mix-number eyebrow is the stable per-row anchor; themes render as
    // spans rather than headings.
    const order = screen.getAllByText(/^mystery mix \d+$/i).map((el) => el.textContent);

    expect(order).toEqual([
      "mystery mix 3", // active — open_voting
      "mystery mix 4", // upcoming, by number
      "mystery mix 5",
      "mystery mix 1", // closed, by number
      "mystery mix 2",
    ]);
  });

  it("mix order: sorting does not mutate the array it was handed", async () => {
    // `Array.prototype.sort` sorts in place, and the array here is the route's
    // own state. Sorting it directly would reorder React's state behind its back.
    const mixes = [
      closedMix({ id: "m1", mix_number: 1, theme: "One", state: "closed" }),
      closedMix({ id: "m2", mix_number: 2, theme: "Two", state: "open_voting" }),
    ];
    mockGetMixes.mockResolvedValue(mixes);
    renderClub();

    await screen.findByRole("heading", { name: "Friday Mixtape" });

    expect(mixes.map((m) => m.id)).toEqual(["m1", "m2"]);
  });

  it("isOrganizer: organizer controls present when userId === organizer_id", async () => {
    setAuth(ORGANIZER_ID);
    renderClub();

    await screen.findByRole("heading", { name: "Friday Mixtape" });
    // The edit toggle is organizer-only.
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    // Remove is shown on the non-organizer member row.
    expect(screen.getByRole("button", { name: /^remove$/i })).toBeInTheDocument();
  });

  it("not organizer: organizer controls absent when userId !== organizer_id", async () => {
    setAuth(MEMBER_ID);
    renderClub();

    await screen.findByRole("heading", { name: "Friday Mixtape" });
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^remove$/i })).not.toBeInTheDocument();
  });

  it("MYS-246: a plain (non-admin) member never sees the invite section", async () => {
    setAuth(MEMBER_ID);
    renderClub();

    await screen.findByRole("heading", { name: "Friday Mixtape" });
    expect(screen.queryByRole("heading", { name: /^invite$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^invite$/i })).not.toBeInTheDocument();
  });

  it("error: getClub rejecting with 403 shows a calm error and does not crash", async () => {
    mockGetClub.mockRejectedValue(new ApiError(403, "forbidden"));
    renderClub();

    // The error state renders a back affordance; the screen does not throw.
    expect(await screen.findByRole("button", { name: /^back$/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Friday Mixtape" })).not.toBeInTheDocument();
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    await user.click(screen.getByRole("button", { name: /^edit$/i }));

    expect(
      (container.querySelector("#edit-submission-window-days") as HTMLInputElement).value,
    ).toBe("4");
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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

    expect(
      await screen.findByText(/submission windows need at least 4 hours\./i),
    ).toBeInTheDocument();
    expect(mockUpdateClub).not.toHaveBeenCalled();
  });

  it("organizer remove: clicking remove on a non-organizer calls removeMember", async () => {
    mockRemoveMember.mockResolvedValue(undefined);
    const user = userEvent.setup();

    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    await user.click(screen.getByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(mockRemoveMember).toHaveBeenCalledTimes(1));
    expect(mockRemoveMember).toHaveBeenCalledWith("club-1", MEMBER_ID);
  });

  // --- Member blocking (MysteryMixClub-4vii.42, Guideline 1.2) ---

  it("block: the block action sits on every non-self row, not your own", async () => {
    setAuth(ORGANIZER_ID);
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    expect(screen.getByRole("button", { name: /^block bo ?--/i })).toBeInTheDocument();
    // Your own row carries no self-block control.
    expect(screen.queryByRole("button", { name: /^block ada ?--/i })).not.toBeInTheDocument();
  });

  it("block: clicking 'block' calls the api, then the row shows the blocked badge + an unblock action", async () => {
    const user = userEvent.setup();
    setAuth(ORGANIZER_ID);
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    await user.click(screen.getByRole("button", { name: /^block bo ?--/i }));

    await waitFor(() => expect(mockBlockUser).toHaveBeenCalledWith(MEMBER_ID));
    expect(await screen.findByText("blocked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^unblock bo$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^block bo ?--/i })).not.toBeInTheDocument();
    // A steady-state reminder of what blocking does appears once anyone is blocked.
    expect(
      screen.getByText(/a blocked member's notes are hidden from you/i),
    ).toBeInTheDocument();
  });

  it("unblock: a member marked blocked_by_me gets an 'unblock' action that restores the plain row", async () => {
    const user = userEvent.setup();
    mockGetClubMembers.mockResolvedValue([
      ...members().map((m) =>
        m.user_id === MEMBER_ID ? { ...m, blocked_by_me: true } : m,
      ),
    ]);
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    // Server-reported state shows the badge + unblock (which the aria-label
    // names specifically), never the block action.
    expect(screen.getByText("blocked")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^unblock bo$/i }));

    await waitFor(() => expect(mockUnblockUser).toHaveBeenCalledWith(MEMBER_ID));
    await waitFor(() => expect(screen.queryByText("blocked")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^block bo ?--/i })).toBeInTheDocument();
    expect(
      screen.queryByText(/a blocked member's notes are hidden from you/i),
    ).not.toBeInTheDocument();
  });

  it("narrow rows (MysteryMixClub-4vii.47): every member control stays present, wrap-capable, and tappable at iPhone portrait width", async () => {
    // Dawn's repro on iPhone 17 Pro: with organizer controls + a blocked
    // badge the nowrap row pushed Unblock past the right edge. The fix wraps
    // the name cluster and the actions cluster; this test pins the wrapping
    // structure and that unblock still reverses the block from the same row.
    window.innerWidth = 393; // iPhone portrait
    window.dispatchEvent(new Event("resize"));

    const user = userEvent.setup();
    setAuth(ORGANIZER_ID); // organizer controls = the cramped case
    mockGetClubMembers.mockResolvedValue([
      ...members().map((m) =>
        m.user_id === MEMBER_ID ? { ...m, blocked_by_me: true } : m,
      ),
    ]);
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    const unblock = screen.getByRole("button", { name: /^unblock bo$/i });
    const makeAdmin = screen.getByRole("button", { name: /make admin/i });
    const remove = screen.getByRole("button", { name: /^remove$/i });
    expect(screen.getByText("blocked")).toBeInTheDocument();

    // Both halves of the cramped row wrap now, so nothing can extend past
    // the right edge; pin that structure against a relapse to fixed rows.
    const row = unblock.closest("li");
    expect(row).not.toBeNull();
    const rowFlex = row!.querySelector("div");
    expect(rowFlex?.className).toContain("flex-wrap");
    expect(unblock.closest("span")?.className).toContain("flex-wrap");

    // ...and the reversal control still works from the same row.
    await user.click(unblock);
    await waitFor(() => expect(mockUnblockUser).toHaveBeenCalledWith(MEMBER_ID));
    expect(makeAdmin).toBeEnabled();
    expect(remove).toBeEnabled();
  });

  it("block failure: a calm error lands by the list and the row keeps its block action", async () => {
    const user = userEvent.setup();
    mockBlockUser.mockRejectedValue(new Error("boom"));
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    await user.click(screen.getByRole("button", { name: /^block bo ?--/i }));

    expect(await screen.findByText(/couldn't block that member/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^block bo ?--/i })).toBeInTheDocument();
  });

  // --- Co-organizer promote/demote (MYS-99) ---

  it("co-organizer badge: renders for a member with is_admin && !is_organizer, not for the fixed organizer or a plain member", async () => {
    const roster = membersWithCoOrganizer();
    mockGetClubMembers.mockResolvedValue(roster);
    mockGetClubLeaderboard.mockResolvedValue(leaderboardFor(roster));

    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    const makeAdminBtn = screen.getByRole("button", { name: /^make admin$/i });
    await user.click(makeAdminBtn);

    expect(mockUpdateMemberRole).toHaveBeenCalledWith("club-1", MEMBER_ID, "admin");
    expect(await screen.findByText(/couldn't update that member's role/i)).toBeInTheDocument();
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
      // Remove is available on both the plain member's row and the other
      // co-organizer's row (never the fixed organizer's), per showRoleAndRemove.
      expect(screen.getAllByRole("button", { name: /^remove$/i })).toHaveLength(2);
    });

    it("a co-organizer viewer sees BOTH the delete-club and leave-club sections", async () => {
      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      expect(screen.getByRole("button", { name: /^delete club$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^leave club$/i })).toBeInTheDocument();
    });

    it("MYS-246: a co-organizer viewer sees the invite section", async () => {
      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      expect(screen.getByRole("heading", { name: /^invite$/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /^invite$/i })).toBeInTheDocument();
    });
  });

  it("the fixed organizer sees only the delete-club section, not leave-club", async () => {
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    expect(screen.getByRole("button", { name: /^delete club$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^leave club$/i })).not.toBeInTheDocument();
  });

  it("a plain member sees only the leave-club section, not delete-club", async () => {
    setAuth(MEMBER_ID);
    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    expect(screen.queryByRole("button", { name: /^delete club$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^leave club$/i })).toBeInTheDocument();
  });

  it("nav: the TopNav home link navigates to /home", async () => {
    const user = userEvent.setup();

    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    // Two "home" controls in the TopNav (ring mark + text link); either routes home.
    await user.click(screen.getAllByRole("button", { name: /^my clubs$/i })[1]);

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });
    expect(await screen.findByText(/^closes /i)).toBeInTheDocument();
  });

  it("closed mix: shows the single winner and most-noted pick on the card", async () => {
    mockGetMixes.mockResolvedValue([closedMix()]);
    mockGetResults.mockResolvedValue(resultsWith());

    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    expect(await screen.findByText("winner")).toBeInTheDocument();
    expect(screen.getByText("Wren")).toBeInTheDocument();
    expect(screen.getByText("most noted")).toBeInTheDocument();
    expect(screen.getByText("Strange Currencies")).toBeInTheDocument();
    expect(mockGetResults).toHaveBeenCalledWith("mix-1");
  });

  it("closed mix: the reveal is an amber callout, and its values stay bright", async () => {
    mockGetMixes.mockResolvedValue([closedMix()]);
    mockGetResults.mockResolvedValue(resultsWith());

    renderClub();
    await screen.findByRole("heading", { name: "Friday Mixtape" });

    const block = (await screen.findByText("winner")).closest("dl")!;

    // A tinted surface with its own edge, not just amber text — the mix number
    // above is already `accent`, so text alone would blend into it.
    expect(block.className).toContain("bg-accent-surface");
    // The tint is only 1.07:1 against `card`, so the hairline is what actually
    // draws the edge. Losing it would leave the block invisible as an object.
    expect(block.className).toContain("border-accent-hairline");

    // The names and titles stay `foreground` (16.63:1) rather than going amber
    // too, so the result itself remains the most legible thing in the block.
    expect(screen.getByText("Wren").className).toContain("text-foreground");
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });

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
    await screen.findByRole("heading", { name: "Friday Mixtape" });
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
    await screen.findByRole("heading", { name: "Friday Mixtape" });
    expect(screen.queryByText(/of 0 voted/i)).not.toBeInTheDocument();
  });

  describe("open mix from the club home list (MysteryMixClub-4vii.4)", () => {
    it("a themed pending mix's 'open mix' button opens it for submissions", async () => {
      const pending = closedMix({ id: "mix-pending", state: "pending", theme: "late summer feels" });
      mockGetMixes.mockResolvedValue([pending]);
      mockUpdateMix.mockResolvedValue({ ...pending, state: "open_submission" });

      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      await userEvent.click(screen.getByRole("button", { name: /^open mix$/i }));

      expect(mockUpdateMix).toHaveBeenCalledWith("mix-pending", { state: "open_submission" });
      // Reflects the server's returned state (patched into local state)
      // rather than a refetch — "upcoming" is gone, its open_submission
      // label is showing.
      expect(await screen.findByText(/^submissions open$/i)).toBeInTheDocument();
      expect(screen.queryByText(/^upcoming$/i)).not.toBeInTheDocument();
    });

    it("an untitled pending mix has no 'open mix' button, and explains why", async () => {
      mockGetMixes.mockResolvedValue([
        closedMix({ id: "mix-untitled", state: "pending", theme: null }),
      ]);

      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      expect(screen.queryByRole("button", { name: /^open mix$/i })).not.toBeInTheDocument();
      expect(
        screen.getByText(/add a theme before you can open this mystery mix/i),
      ).toBeInTheDocument();
    });

    it("a failed open shows a calm error without navigating away", async () => {
      mockGetMixes.mockResolvedValue([
        closedMix({ id: "mix-pending", state: "pending", theme: "late summer feels" }),
      ]);
      mockUpdateMix.mockRejectedValue(new ApiError(409, "set a theme before opening this mystery mix"));

      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      await userEvent.click(screen.getByRole("button", { name: /^open mix$/i }));

      expect(
        await screen.findByText(/set a theme before opening this mystery mix/i),
      ).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Friday Mixtape" })).toBeInTheDocument();
    });

    it("a themed mix #2 has no 'open mix' button while mix #1 is still pending, and explains why", async () => {
      mockGetMixes.mockResolvedValue([
        closedMix({ id: "mix-1", mix_number: 1, state: "pending", theme: "mix one" }),
        closedMix({ id: "mix-2", mix_number: 2, state: "pending", theme: "mix two" }),
      ]);

      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      // Only mix #1 (the first mix) is eligible — one "open mix" button, not two.
      expect(screen.getAllByRole("button", { name: /^open mix$/i })).toHaveLength(1);
      expect(
        screen.getByText(/mystery mix 1 must close before this one can open/i),
      ).toBeInTheDocument();
    });

    it("mix #2's 'open mix' button appears once mix #1 has closed", async () => {
      mockGetMixes.mockResolvedValue([
        closedMix({ id: "mix-1", mix_number: 1, state: "closed" }),
        closedMix({ id: "mix-2", mix_number: 2, state: "pending", theme: "mix two" }),
      ]);

      renderClub();
      await screen.findByRole("heading", { name: "Friday Mixtape" });

      expect(screen.getAllByRole("button", { name: /^open mix$/i })).toHaveLength(1);
    });
  });

  describe("club-invite welcome guide (MysteryMixClub-6eo8)", () => {
    beforeEach(() => {
      localStorage.clear();
      // Global setup's own beforeEach marks the release-notes popup seen
      // before this one runs; the clear() above wipes that back out, so redo
      // it here or that unrelated modal renders too and getByRole("dialog")
      // stops being unambiguous.
      markLatestReleaseSeen();
    });

    it("auto-shows when the caller just joined this club via invite", async () => {
      markJustJoinedClub("club-1");
      renderClub("club-1");

      const dialog = await screen.findByRole("dialog");
      expect(dialog).toHaveAccessibleName(/you're in/i);
      // The real club name replaces the mockup's placeholder "the listening room".
      expect(within(dialog).getByText(/friday/i)).toBeInTheDocument();
      expect(within(dialog).getByText(/mixtape/i)).toBeInTheDocument();
      for (const step of [
        "join your friends",
        "submit your songs",
        "listen to the mix",
        "vote for your favorites",
      ]) {
        expect(within(dialog).getByText(step)).toBeInTheDocument();
      }
    });

    it("does not show on an ordinary visit (no just-joined flag set)", async () => {
      renderClub("club-1");

      await screen.findByRole("heading", { name: "Friday Mixtape" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("does not show while the club is still loading", async () => {
      let resolveClub: (club: Club) => void = () => {};
      mockGetClub.mockReturnValue(
        new Promise((resolve) => {
          resolveClub = resolve;
        }),
      );
      markJustJoinedClub("club-1");
      renderClub("club-1");

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      resolveClub(clubWith());
      expect(await screen.findByRole("dialog")).toBeInTheDocument();
    });

    it("does not show when the club fails to load", async () => {
      mockGetClub.mockRejectedValue(new ApiError(500, "boom"));
      markJustJoinedClub("club-1");
      renderClub("club-1");

      await screen.findByText("boom");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("the just-joined flag is one-shot: a second club-home mount never auto-shows from the same flag", async () => {
      markJustJoinedClub("club-1");
      const { unmount } = renderClub("club-1");
      await screen.findByRole("dialog");
      unmount();

      renderClub("club-1");
      await screen.findByRole("heading", { name: "Friday Mixtape" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("dismissing (close button) persists per account and leaves the member in the club", async () => {
      const user = userEvent.setup();
      markJustJoinedClub("club-1");
      renderClub("club-1");

      await screen.findByRole("dialog");
      await user.click(screen.getByRole("button", { name: /dismiss welcome guide/i }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Friday Mixtape" })).toBeInTheDocument();
      expect(isGuideDismissed("invite", ORGANIZER_ID)).toBe(true);
    });

    it("the primary CTA ('let's go') dismisses without navigating away", async () => {
      const user = userEvent.setup();
      markJustJoinedClub("club-1");
      renderClub("club-1");

      const dialog = await screen.findByRole("dialog");
      await user.click(within(dialog).getByRole("button", { name: "let's go" }));

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Friday Mixtape" })).toBeInTheDocument();
    });

    it("Escape dismisses the guide", async () => {
      const user = userEvent.setup();
      markJustJoinedClub("club-1");
      renderClub("club-1");

      await screen.findByRole("dialog");
      await user.keyboard("{Escape}");

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });

    it("'how it works' reopens the guide at any time, even without ever having joined via invite", async () => {
      const user = userEvent.setup();
      dismissGuide("invite", ORGANIZER_ID);
      renderClub("club-1");

      await screen.findByRole("heading", { name: "Friday Mixtape" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /how it works/i }));

      expect(await screen.findByRole("dialog")).toBeInTheDocument();
    });
  });
});
