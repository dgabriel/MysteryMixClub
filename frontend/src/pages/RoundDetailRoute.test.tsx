import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RoundDetailRoute } from "./RoundDetailRoute";
import {
  addNote,
  castVotes,
  getLeague,
  getLeagueMembers,
  getMySubmission,
  getMyVotes,
  getNotes,
  getPlaylist,
  getRound,
  getRoundSubmissions,
  updateRound,
} from "../services/api";
import type { League, PlaylistEntry, Round, SubmissionResult } from "../services/api";
import { useAuth } from "../hooks/useAuth";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getRound: vi.fn(),
    getLeague: vi.fn(),
    getMySubmission: vi.fn(),
    getPlaylist: vi.fn(),
    getRoundSubmissions: vi.fn(),
    getLeagueMembers: vi.fn(),
    updateRound: vi.fn(),
    submitSong: vi.fn(),
    getMyVotes: vi.fn(),
    castVotes: vi.fn(),
    getNotes: vi.fn(),
    addNote: vi.fn(),
  };
});
vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetRound = vi.mocked(getRound);
const mockGetLeague = vi.mocked(getLeague);
const mockGetMine = vi.mocked(getMySubmission);
const mockGetPlaylist = vi.mocked(getPlaylist);
const mockGetReveal = vi.mocked(getRoundSubmissions);
const mockGetMembers = vi.mocked(getLeagueMembers);
const mockUpdateRound = vi.mocked(updateRound);
const mockGetMyVotes = vi.mocked(getMyVotes);
const mockCastVotes = vi.mocked(castVotes);
const mockGetNotes = vi.mocked(getNotes);
const mockAddNote = vi.mocked(addNote);
const mockUseAuth = vi.mocked(useAuth);

const ORGANIZER = "org-1";
const OTHER = "user-2";

function round(overrides: Partial<Round> = {}): Round {
  return {
    id: "r1",
    league_id: "lg1",
    round_number: 1,
    theme: "late summer feels",
    state: "open_submission",
    submission_deadline: null,
    voting_deadline: null,
    votes_per_player: 3,
    created_at: "2026-01-01T00:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function league(): League {
  return {
    id: "lg1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: ORGANIZER,
    total_rounds: 6,
    votes_per_player: 3,
    current_round: 1,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: null,
  };
}

function entry(overrides: Partial<PlaylistEntry> = {}): PlaylistEntry {
  return {
    submission_id: "p1",
    isrc: "I1",
    title: "Debaser",
    artist: "Pixies",
    album: null,
    album_art_url: null,
    participation_mode: "playing",
    platforms: { spotify: "https://s" },
    preferred_url: "https://s",
    ...overrides,
  };
}

function mine(overrides: Partial<SubmissionResult> = {}): SubmissionResult {
  return {
    id: "s-mine",
    round_id: "r1",
    user_id: ORGANIZER,
    isrc: "IM",
    title: "My Song",
    artist: "Me",
    album: null,
    album_art_url: null,
    note: null,
    participation_mode: "playing",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function setAuth(userId: string) {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: "x",
    userId,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function renderRound() {
  return render(
    <MemoryRouter initialEntries={["/rounds/r1"]}>
      <Routes>
        <Route path="/rounds/:id" element={<RoundDetailRoute />} />
        <Route path="/leagues/:id" element={<div>LEAGUE PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RoundDetailRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetRound.mockResolvedValue(round());
    mockGetLeague.mockResolvedValue(league());
    mockGetMine.mockResolvedValue(null);
    mockGetPlaylist.mockResolvedValue({
      round_id: "r1",
      round_number: 1,
      theme: "t",
      state: "open_voting",
      entries: [],
    });
    mockGetReveal.mockResolvedValue([]);
    mockGetMembers.mockResolvedValue([]);
    mockGetMyVotes.mockResolvedValue({
      round_id: "r1",
      submission_ids: [],
      count: 0,
      votes_per_player: 3,
    });
    mockCastVotes.mockResolvedValue({
      round_id: "r1",
      submission_ids: [],
      count: 0,
      votes_per_player: 3,
    });
    mockGetNotes.mockResolvedValue([]);
    mockAddNote.mockResolvedValue({
      id: "n1",
      submission_id: "p1",
      round_id: "r1",
      author_id: OTHER,
      author_display_name: "Bob",
      body: "lovely pick",
      created_at: "2026-01-01T00:00:00Z",
    });
    setAuth(ORGANIZER);
  });

  it("open_submission, no submission: shows the submit-a-song card", async () => {
    renderRound();
    expect(await screen.findByText("late summer feels")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /submit a song/i })).toBeInTheDocument();
  });

  it("open_submission with an existing submission: shows it + change affordance", async () => {
    const mine: SubmissionResult = {
      id: "s1",
      round_id: "r1",
      user_id: ORGANIZER,
      isrc: "I1",
      title: "Take on Me",
      artist: "a-ha",
      album: null,
      album_art_url: null,
      note: null,
      participation_mode: "playing",
      created_at: "2026-01-01T00:00:00Z",
    };
    mockGetMine.mockResolvedValue(mine);
    renderRound();
    expect(await screen.findByText("Take on Me")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /change song/i })).toBeInTheDocument();
  });

  it("organizer can open voting; advancing calls updateRound", async () => {
    const user = userEvent.setup();
    renderRound();
    const btn = await screen.findByRole("button", { name: /open voting/i });
    await user.click(btn);
    expect(mockUpdateRound).toHaveBeenCalledWith("r1", { state: "open_voting" });
  });

  it("non-organizer sees no advance control", async () => {
    setAuth(OTHER);
    renderRound();
    await screen.findByText("late summer feels");
    expect(screen.queryByRole("button", { name: /open voting/i })).not.toBeInTheDocument();
  });

  it("open_voting: renders the playlist with platform links", async () => {
    mockGetRound.mockResolvedValue(round({ state: "open_voting" }));
    const entries: PlaylistEntry[] = [
      {
        submission_id: "p1",
        isrc: "I1",
        title: "Debaser",
        artist: "Pixies",
        album: null,
        album_art_url: null,
        participation_mode: "playing",
        platforms: { spotify: "https://s", deezer: "https://d" },
        preferred_url: "https://s",
      },
    ];
    mockGetPlaylist.mockResolvedValue({
      round_id: "r1",
      round_number: 1,
      theme: "t",
      state: "open_voting",
      entries,
    });
    renderRound();
    expect(await screen.findByText("Debaser")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /on Spotify/i })).toHaveAttribute("href", "https://s");
    expect(screen.getByRole("button", { name: /close round/i })).toBeInTheDocument();
  });

  it("closed: reveals submissions with submitter names", async () => {
    mockGetRound.mockResolvedValue(round({ state: "closed" }));
    mockGetReveal.mockResolvedValue([
      {
        id: "s1",
        round_id: "r1",
        user_id: OTHER,
        isrc: "I1",
        title: "Bad Guy",
        artist: "Billie Eilish",
        album: null,
        album_art_url: null,
        note: "a banger",
        participation_mode: "playing",
        created_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mockGetMembers.mockResolvedValue([
      { user_id: OTHER, display_name: "Bob", joined_at: "x", is_organizer: false },
    ]);
    renderRound();
    expect(await screen.findByText("Bad Guy")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText(/a banger/)).toBeInTheDocument();
  });

  describe("open_voting voting UX (MYS-20)", () => {
    /** Put the round into open_voting with the given playlist entries, and a
     *  caller submission (so participation_mode is known) defaulting to playing. */
    function setupVoting(opts: {
      entries: PlaylistEntry[];
      votesPerPlayer?: number;
      myVotes?: string[];
      mine?: SubmissionResult | null;
    }) {
      const vpp = opts.votesPerPlayer ?? 3;
      mockGetRound.mockResolvedValue(round({ state: "open_voting", votes_per_player: vpp }));
      mockGetPlaylist.mockResolvedValue({
        round_id: "r1",
        round_number: 1,
        theme: "t",
        state: "open_voting",
        entries: opts.entries,
      });
      mockGetMyVotes.mockResolvedValue({
        round_id: "r1",
        submission_ids: opts.myVotes ?? [],
        count: (opts.myVotes ?? []).length,
        votes_per_player: vpp,
      });
      // Default: a playing submission so the caller is a voter.
      mockGetMine.mockResolvedValue(opts.mine === undefined ? mine() : opts.mine);
    }

    it("playing voter sees votable entries as toggles, a counter, and pre-selection from getMyVotes", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey", artist: "Pixies" }),
        ],
        myVotes: ["p1"],
      });
      renderRound();

      const debaser = await screen.findByRole("button", { name: /Debaser/i });
      const hey = screen.getByRole("button", { name: /Hey/i });
      // pre-selected from getMyVotes
      expect(debaser).toHaveAttribute("aria-pressed", "true");
      expect(hey).toHaveAttribute("aria-pressed", "false");
      // live counter reflects the seeded selection
      expect(screen.getByText("1 / 3 selected")).toBeInTheDocument();
    });

    it("toggling selects/deselects and updates the counter", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        myVotes: [],
      });
      renderRound();

      const debaser = await screen.findByRole("button", { name: /Debaser/i });
      expect(screen.getByText("0 / 3 selected")).toBeInTheDocument();

      await user.click(debaser);
      expect(debaser).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByText("1 / 3 selected")).toBeInTheDocument();

      await user.click(debaser);
      expect(debaser).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByText("0 / 3 selected")).toBeInTheDocument();
    });

    it("at the votes_per_player limit, unselected toggles are disabled but deselect still works", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        votesPerPlayer: 1,
        myVotes: ["p1"],
      });
      renderRound();

      const debaser = await screen.findByRole("button", { name: /Debaser/i });
      const hey = screen.getByRole("button", { name: /Hey/i });
      expect(screen.getByText("1 / 1 selected")).toBeInTheDocument();
      // at limit: the unselected entry is disabled
      expect(hey).toBeDisabled();
      // the selected entry can still be deselected
      expect(debaser).not.toBeDisabled();

      await user.click(debaser);
      expect(debaser).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByText("0 / 1 selected")).toBeInTheDocument();
      // now under the limit, the previously-disabled toggle is enabled again
      expect(hey).not.toBeDisabled();
    });

    it("cast votes calls castVotes with the selected submission_ids and shows the confirmation", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        myVotes: [],
      });
      mockCastVotes.mockResolvedValue({
        round_id: "r1",
        submission_ids: ["p1"],
        count: 1,
        votes_per_player: 3,
      });
      renderRound();

      const debaser = await screen.findByRole("button", { name: /Debaser/i });
      await user.click(debaser);
      await user.click(screen.getByRole("button", { name: /cast votes/i }));

      expect(mockCastVotes).toHaveBeenCalledWith("r1", ["p1"]);
      expect(await screen.findByText(/votes saved/i)).toBeInTheDocument();
    });

    it("cast votes button is disabled when nothing is selected", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
      });
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      expect(screen.getByRole("button", { name: /cast votes/i })).toBeDisabled();
    });

    it("vibing entries appear in the just-vibing section, are not toggles, and show the warm copy", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({
            submission_id: "v1",
            title: "Ambient Drift",
            participation_mode: "vibing",
          }),
        ],
        myVotes: [],
      });
      renderRound();

      // the vibing track is rendered, but NOT as a toggle button
      await screen.findByRole("button", { name: /Debaser/i });
      expect(screen.getByText("Ambient Drift")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Ambient Drift/i })).not.toBeInTheDocument();
      // the warm helper copy + section heading ("just vibing" also appears as a
      // badge on the entry, so target the section heading specifically)
      expect(screen.getByRole("heading", { name: /just vibing/i })).toBeInTheDocument();
      expect(screen.getByText(/along for the ride/i)).toBeInTheDocument();
    });

    it("a caller who is themselves vibing sees no vote controls, a sit-out message, and still the playlist", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
        mine: mine({ participation_mode: "vibing" }),
      });
      renderRound();

      expect(await screen.findByText(/you sit voting out/i)).toBeInTheDocument();
      // no vote controls
      expect(screen.queryByRole("button", { name: /cast votes/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Debaser/i })).not.toBeInTheDocument();
      // playlist still visible
      expect(screen.getByText("Debaser")).toBeInTheDocument();
    });

    it("a castVotes ApiError surfaces in the actionError region", async () => {
      const user = userEvent.setup();
      const { ApiError } =
        await vi.importActual<typeof import("../services/api")>("../services/api");
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
      });
      mockCastVotes.mockRejectedValue(new ApiError(403, "you can't vote for your own song"));
      renderRound();

      const debaser = await screen.findByRole("button", { name: /Debaser/i });
      await user.click(debaser);
      await user.click(screen.getByRole("button", { name: /cast votes/i }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/you can't vote for your own song/i);
    });
  });

  describe("open_voting notes UX (MYS-21)", () => {
    function setupVoting(opts: { entries: PlaylistEntry[]; mine?: SubmissionResult | null }) {
      mockGetRound.mockResolvedValue(round({ state: "open_voting" }));
      mockGetPlaylist.mockResolvedValue({
        round_id: "r1",
        round_number: 1,
        theme: "t",
        state: "open_voting",
        entries: opts.entries,
      });
      mockGetMyVotes.mockResolvedValue({
        round_id: "r1",
        submission_ids: [],
        count: 0,
        votes_per_player: 3,
      });
      mockGetMine.mockResolvedValue(opts.mine === undefined ? mine() : opts.mine);
    }

    /** The <li> that wraps a single playlist card, located by its song title. */
    function cardFor(title: string): HTMLElement {
      const heading = screen.getByText(title);
      const li = heading.closest("li");
      if (!li) throw new Error(`no card <li> found for "${title}"`);
      return li as HTMLElement;
    }

    it("a just-vibing card shows the leave-a-note affordance and the calm framing", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({
            submission_id: "v1",
            title: "Ambient Drift",
            participation_mode: "vibing",
          }),
        ],
      });
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      const vibingCard = cardFor("Ambient Drift");

      // affordance present on the vibing card
      const leaveNote = within(vibingCard).getByRole("button", { name: /leave a note/i });
      expect(leaveNote).toBeInTheDocument();

      // the calm hint only appears once the composer is opened
      expect(
        within(vibingCard).queryByText(/can't vote on this one — leave a note instead/i),
      ).not.toBeInTheDocument();
      await user.click(leaveNote);
      expect(
        within(vibingCard).getByText(/can't vote on this one — leave a note instead/i),
      ).toBeInTheDocument();
    });

    it("revealing notes calls getNotes for that submission and renders body + author", async () => {
      const user = userEvent.setup();
      setupVoting({ entries: [entry({ submission_id: "p1", title: "Debaser" })] });
      mockGetNotes.mockResolvedValue([
        {
          id: "n1",
          submission_id: "p1",
          round_id: "r1",
          author_id: OTHER,
          author_display_name: "Bob",
          body: "this slaps",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]);
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      const card = cardFor("Debaser");
      await user.click(within(card).getByRole("button", { name: /^notes$/i }));

      expect(mockGetNotes).toHaveBeenCalledWith("p1");
      expect(await within(card).findByText("this slaps")).toBeInTheDocument();
      expect(within(card).getByText("Bob")).toBeInTheDocument();
    });

    it("revealing a submission with no notes shows the empty state", async () => {
      const user = userEvent.setup();
      setupVoting({ entries: [entry({ submission_id: "p1", title: "Debaser" })] });
      mockGetNotes.mockResolvedValue([]);
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      const card = cardFor("Debaser");
      await user.click(within(card).getByRole("button", { name: /^notes$/i }));

      expect(mockGetNotes).toHaveBeenCalledWith("p1");
      expect(await within(card).findByText(/no notes yet/i)).toBeInTheDocument();
    });

    it("composer: typing updates the N/280 counter, submit disabled when empty, then addNote appends and collapses", async () => {
      const user = userEvent.setup();
      setupVoting({ entries: [entry({ submission_id: "p1", title: "Debaser" })] });
      mockGetNotes.mockResolvedValue([]);
      mockAddNote.mockResolvedValue({
        id: "n1",
        submission_id: "p1",
        round_id: "r1",
        author_id: OTHER,
        author_display_name: "Bob",
        body: "great taste",
        created_at: "2026-01-01T00:00:00Z",
      });
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      const card = cardFor("Debaser");
      await user.click(within(card).getByRole("button", { name: /leave a note/i }));

      // empty draft → counter 0/280, submit disabled
      expect(within(card).getByText("0 / 280")).toBeInTheDocument();
      const leaveNoteBtn = within(card).getByRole("button", { name: /leave note/i });
      expect(leaveNoteBtn).toBeDisabled();

      const textarea = within(card).getByRole("textbox");
      await user.type(textarea, "great taste");
      expect(within(card).getByText("11 / 280")).toBeInTheDocument();
      expect(leaveNoteBtn).not.toBeDisabled();

      await user.click(leaveNoteBtn);

      expect(mockAddNote).toHaveBeenCalledWith("p1", "great taste");
      // the new note appears
      expect(await within(card).findByText("great taste")).toBeInTheDocument();
      expect(within(card).getByText("Bob")).toBeInTheDocument();
      // composer collapsed: textarea gone, leave-a-note affordance back
      expect(within(card).queryByRole("textbox")).not.toBeInTheDocument();
      expect(within(card).getByRole("button", { name: /leave a note/i })).toBeInTheDocument();
    });

    it("an addNote ApiError surfaces in the actionError alert region", async () => {
      const user = userEvent.setup();
      const { ApiError } =
        await vi.importActual<typeof import("../services/api")>("../services/api");
      setupVoting({ entries: [entry({ submission_id: "p1", title: "Debaser" })] });
      mockGetNotes.mockResolvedValue([]);
      mockAddNote.mockRejectedValue(
        new ApiError(409, "notes are only allowed while voting is open"),
      );
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      const card = cardFor("Debaser");
      await user.click(within(card).getByRole("button", { name: /leave a note/i }));
      await user.type(within(card).getByRole("textbox"), "nope");
      await user.click(within(card).getByRole("button", { name: /leave note/i }));

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(/notes are only allowed while voting is open/i);
    });

    it("a votable (playing) card exposes the notes affordance without losing its vote toggle", async () => {
      const user = userEvent.setup();
      setupVoting({ entries: [entry({ submission_id: "p1", title: "Debaser" })] });
      mockGetNotes.mockResolvedValue([]);
      renderRound();

      // the vote toggle still works
      const toggle = await screen.findByRole("button", { name: /Debaser/i });
      expect(toggle).toHaveAttribute("aria-pressed", "false");
      await user.click(toggle);
      expect(toggle).toHaveAttribute("aria-pressed", "true");

      // and the same card exposes a notes affordance
      const card = cardFor("Debaser");
      expect(within(card).getByRole("button", { name: /^notes$/i })).toBeInTheDocument();
      expect(within(card).getByRole("button", { name: /leave a note/i })).toBeInTheDocument();
    });

    it("notes affordances do NOT appear in the closed/reveal view", async () => {
      mockGetRound.mockResolvedValue(round({ state: "closed" }));
      mockGetReveal.mockResolvedValue([
        {
          id: "s1",
          round_id: "r1",
          user_id: OTHER,
          isrc: "I1",
          title: "Bad Guy",
          artist: "Billie Eilish",
          album: null,
          album_art_url: null,
          note: "a banger",
          participation_mode: "playing",
          created_at: "2026-01-01T00:00:00Z",
        },
      ]);
      mockGetMembers.mockResolvedValue([
        { user_id: OTHER, display_name: "Bob", joined_at: "x", is_organizer: false },
      ]);
      renderRound();

      await screen.findByText("Bad Guy");
      expect(screen.queryByRole("button", { name: /leave a note/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^notes$/i })).not.toBeInTheDocument();
      expect(mockGetNotes).not.toHaveBeenCalled();
    });
  });
});
