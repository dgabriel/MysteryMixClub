import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RoundDetailRoute } from "./RoundDetailRoute";
import {
  addNote,
  castVotes,
  getLeague,
  getMySubmission,
  getMyVotes,
  getNotes,
  getPlaylist,
  getResults,
  getRound,
  updateRound,
} from "../services/api";
import type { League, PlaylistEntry, Round, RoundResults, SubmissionResult } from "../services/api";
import { useAuth } from "../hooks/useAuth";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getRound: vi.fn(),
    getLeague: vi.fn(),
    getMySubmission: vi.fn(),
    getPlaylist: vi.fn(),
    getResults: vi.fn(),
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
const mockGetResults = vi.mocked(getResults);
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
    description: null,
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
    is_own: false,
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

function results(overrides: Partial<RoundResults> = {}): RoundResults {
  return {
    round_id: "r1",
    round_number: 1,
    theme: "late summer feels",
    state: "closed",
    submissions: [],
    leaderboard: [],
    most_noted: { note_count: 0, winners: [] },
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
      youtube_playlist_url: null,
      youtube_track_count: 0,
    });
    mockGetResults.mockResolvedValue(results());
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
        is_own: false,
      },
    ];
    mockGetPlaylist.mockResolvedValue({
      round_id: "r1",
      round_number: 1,
      theme: "t",
      state: "open_voting",
      entries,
      youtube_playlist_url: null,
      youtube_track_count: 0,
    });
    renderRound();
    expect(await screen.findByText("Debaser")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /on Spotify/i })).toHaveAttribute("href", "https://s");
    expect(screen.getByRole("button", { name: /close round/i })).toBeInTheDocument();
  });

  it("closed: reveals submissions with submitter names", async () => {
    mockGetRound.mockResolvedValue(round({ state: "closed" }));
    mockGetResults.mockResolvedValue(
      results({
        submissions: [
          {
            submission_id: "s1",
            user_id: OTHER,
            submitter_display_name: "Bob",
            isrc: "I1",
            title: "Bad Guy",
            artist: "Billie Eilish",
            album: null,
            album_art_url: null,
            participation_mode: "playing",
            submitter_note: "a banger",
            vote_count: 0,
            notes: [],
          },
        ],
      }),
    );
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
      youtubePlaylistUrl?: string | null;
      youtubeTrackCount?: number;
    }) {
      const vpp = opts.votesPerPlayer ?? 3;
      mockGetRound.mockResolvedValue(round({ state: "open_voting", votes_per_player: vpp }));
      mockGetPlaylist.mockResolvedValue({
        round_id: "r1",
        round_number: 1,
        theme: "t",
        state: "open_voting",
        entries: opts.entries,
        youtube_playlist_url: opts.youtubePlaylistUrl ?? null,
        youtube_track_count: opts.youtubeTrackCount ?? 0,
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

    it("open YouTube affordance: renders a new-tab link to youtube_playlist_url with the N of M count (MYS-78)", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        myVotes: [],
        youtubePlaylistUrl: "https://www.youtube.com/watch_videos?video_ids=a,b",
        youtubeTrackCount: 1,
      });
      renderRound();

      const link = await screen.findByRole("link", { name: /open playlist in youtube/i });
      expect(link).toHaveAttribute(
        "href",
        "https://www.youtube.com/watch_videos?video_ids=a,b",
      );
      expect(link).toHaveAttribute("target", "_blank");
      // N (youtube_track_count) of M (entry count) on YouTube
      expect(screen.getByText("1 of 2 on YouTube")).toBeInTheDocument();
    });

    it("open YouTube affordance: hidden entirely when youtube_playlist_url is null (MYS-78)", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
        youtubePlaylistUrl: null,
      });
      renderRound();

      await screen.findByRole("button", { name: /Debaser/i });
      expect(
        screen.queryByRole("link", { name: /open playlist in youtube/i }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/on YouTube/i)).not.toBeInTheDocument();
    });

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

    it("own song (is_own): marked as yours, not a vote toggle, no notes affordance, not selectable (MYS-73/74/75/77)", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "mine", title: "My Track", is_own: true }),
          entry({ submission_id: "p2", title: "Their Track" }),
        ],
        myVotes: [],
      });
      renderRound();

      await screen.findByText("My Track");
      // clearly marked as yours, with the no-self-vote explanation
      expect(screen.getByText("your submission")).toBeInTheDocument();
      expect(screen.getByText(/can't vote for your own song/i)).toBeInTheDocument();
      // your own song is NOT a vote toggle…
      expect(screen.queryByRole("button", { name: /My Track/i })).not.toBeInTheDocument();
      // …while everyone else's still is
      expect(screen.getByRole("button", { name: /Their Track/i })).toBeInTheDocument();
      // and it doesn't count toward the selectable set
      expect(screen.getByText("0 / 3 selected")).toBeInTheDocument();

      // you can't leave a note on your own submission (MYS-77): the own card has
      // no notes / leave-a-note affordance, while a peer's card still does.
      const ownCard = screen.getByText("My Track").closest("li") as HTMLElement;
      expect(within(ownCard).queryByRole("button", { name: /^notes$/i })).not.toBeInTheDocument();
      expect(
        within(ownCard).queryByRole("button", { name: /leave a note/i }),
      ).not.toBeInTheDocument();
      const peerCard = screen.getByText("Their Track").closest("li") as HTMLElement;
      expect(within(peerCard).getByRole("button", { name: /^notes$/i })).toBeInTheDocument();
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

    it("cast votes button shows a clear busy label while the request is in flight", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
      });
      // Hold the request open so the busy state is observable (MYS-66: the
      // button must read "casting…", never a bare "…").
      let resolveCast: (() => void) | undefined;
      mockCastVotes.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveCast = () =>
              resolve({ round_id: "r1", submission_ids: ["p1"], count: 1, votes_per_player: 3 });
          }),
      );
      renderRound();

      await user.click(await screen.findByRole("button", { name: /Debaser/i }));
      await user.click(screen.getByRole("button", { name: /cast votes/i }));

      expect(await screen.findByRole("button", { name: /casting…/i })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^…$/ })).not.toBeInTheDocument();

      resolveCast?.();
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
        youtube_playlist_url: null,
        youtube_track_count: 0,
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
      mockGetResults.mockResolvedValue(
        results({
          submissions: [
            {
              submission_id: "s1",
              user_id: OTHER,
              submitter_display_name: "Bob",
              isrc: "I1",
              title: "Bad Guy",
              artist: "Billie Eilish",
              album: null,
              album_art_url: null,
              participation_mode: "playing",
              submitter_note: "a banger",
              vote_count: 0,
              notes: [],
            },
          ],
        }),
      );
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      expect(screen.queryByRole("button", { name: /leave a note/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^notes$/i })).not.toBeInTheDocument();
      expect(mockGetNotes).not.toHaveBeenCalled();
    });
  });

  describe("closed reveal / results (MYS-24)", () => {
    /** A revealed submission fixture. */
    function sub(
      overrides: Partial<RoundResults["submissions"][number]> = {},
    ): RoundResults["submissions"][number] {
      return {
        submission_id: "s1",
        user_id: OTHER,
        submitter_display_name: "Bob",
        isrc: "I1",
        title: "Bad Guy",
        artist: "Billie Eilish",
        album: null,
        album_art_url: null,
        participation_mode: "playing",
        submitter_note: null,
        vote_count: 0,
        notes: [],
        ...overrides,
      };
    }

    /** Put the round into closed state with the given results payload. */
    function setupClosed(overrides: Partial<RoundResults> = {}) {
      mockGetRound.mockResolvedValue(round({ state: "closed" }));
      mockGetResults.mockResolvedValue(results(overrides));
    }

    /** The <section> wrapping a heading, by that heading's text. */
    function sectionFor(headingText: RegExp): HTMLElement {
      const heading = screen.getByRole("heading", { name: headingText });
      const section = heading.closest("section");
      if (!section) throw new Error(`no <section> found for heading ${headingText}`);
      return section as HTMLElement;
    }

    /** The <li> card wrapping a submission in the picks list, by its song title.
     *  Scoped to the picks section since a top-voted song also appears in the
     *  Winner(s) highlight (and Most Noted) above. */
    function cardFor(title: string): HTMLElement {
      const picks = sectionFor(/the picks/i);
      const heading = within(picks).getByText(title);
      const li = heading.closest("li");
      if (!li) throw new Error(`no card <li> found for "${title}"`);
      return li as HTMLElement;
    }

    // ----- Most Noted ------------------------------------------------------ //

    it("Most Noted: renders winner title/artist, note count, and all its notes", async () => {
      setupClosed({
        submissions: [sub({ vote_count: 2, notes: [] })],
        most_noted: {
          note_count: 2,
          winners: [
            {
              submission_id: "s1",
              title: "Bad Guy",
              artist: "Billie Eilish",
              note_count: 2,
              notes: [
                { body: "an absolute banger", author_display_name: "Ada", created_at: "x" },
                { body: "haunting bassline", author_display_name: "Cal", created_at: "y" },
              ],
            },
          ],
        },
      });
      renderRound();

      await screen.findByRole("heading", { name: /most noted/i });
      const section = sectionFor(/most noted/i);
      // singular framing copy for a single winner
      expect(within(section).getByText(/the pick that got everyone talking/i)).toBeInTheDocument();
      expect(within(section).getByText("Bad Guy")).toBeInTheDocument();
      expect(within(section).getByText("Billie Eilish")).toBeInTheDocument();
      expect(within(section).getByText("2 notes")).toBeInTheDocument();
      // ALL notes (body + author) shown within the Most Noted section
      expect(within(section).getByText("an absolute banger")).toBeInTheDocument();
      expect(within(section).getByText("Ada")).toBeInTheDocument();
      expect(within(section).getByText("haunting bassline")).toBeInTheDocument();
      expect(within(section).getByText("Cal")).toBeInTheDocument();
    });

    it("Most Noted: a tie renders both winners as co-recognized", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "s1", title: "Bad Guy", vote_count: 2 }),
          sub({ submission_id: "s2", title: "Vienna", artist: "Billy Joel", vote_count: 1 }),
        ],
        most_noted: {
          note_count: 3,
          winners: [
            {
              submission_id: "s1",
              title: "Bad Guy",
              artist: "Billie Eilish",
              note_count: 3,
              notes: [{ body: "loved it", author_display_name: "Ada", created_at: "x" }],
            },
            {
              submission_id: "s2",
              title: "Vienna",
              artist: "Billy Joel",
              note_count: 3,
              notes: [{ body: "timeless", author_display_name: "Cal", created_at: "y" }],
            },
          ],
        },
      });
      renderRound();

      await screen.findByRole("heading", { name: /most noted/i });
      const section = sectionFor(/most noted/i);
      // plural framing copy for a tie
      expect(within(section).getByText(/the picks that got everyone talking/i)).toBeInTheDocument();
      // both winners present in the section
      expect(within(section).getByText("Bad Guy")).toBeInTheDocument();
      expect(within(section).getByText("Vienna")).toBeInTheDocument();
      expect(within(section).getByText("loved it")).toBeInTheDocument();
      expect(within(section).getByText("timeless")).toBeInTheDocument();
    });

    it("Most Noted: section is omitted entirely when there are no winners", async () => {
      setupClosed({
        submissions: [sub({ vote_count: 0 })],
        most_noted: { note_count: 0, winners: [] },
      });
      renderRound();

      // wait for the page to render the picks
      await screen.findByRole("heading", { name: /the picks/i });
      expect(screen.queryByRole("heading", { name: /most noted/i })).not.toBeInTheDocument();
      expect(screen.queryByText(/got everyone talking/i)).not.toBeInTheDocument();
    });

    // ----- Winner(s) by votes (MYS-71) ------------------------------------ //

    it("Winner: highlights the single top-voted song with submitter and vote count", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "s1", user_id: "u-bo", submitter_display_name: "Bo", title: "Bad Guy", vote_count: 3 }),
          sub({
            submission_id: "s2",
            user_id: "u-cal",
            submitter_display_name: "Cal",
            title: "Vienna",
            artist: "Billy Joel",
            vote_count: 1,
          }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /^winner$/i });
      const section = sectionFor(/^winner$/i);
      expect(within(section).getByText("the most votes this round")).toBeInTheDocument();
      expect(within(section).getByText("Bad Guy")).toBeInTheDocument();
      expect(within(section).getByText("3 votes")).toBeInTheDocument();
      // the lower-voted song is not in the winner section
      expect(within(section).queryByText("Vienna")).not.toBeInTheDocument();
    });

    it("Winner: a tie co-recognizes every top-voted song", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "s1", user_id: "u-bo", submitter_display_name: "Bo", title: "Bad Guy", vote_count: 2 }),
          sub({
            submission_id: "s2",
            user_id: "u-cal",
            submitter_display_name: "Cal",
            title: "Vienna",
            artist: "Billy Joel",
            vote_count: 2,
          }),
          sub({
            submission_id: "s3",
            user_id: "u-di",
            submitter_display_name: "Di",
            title: "Roygbiv",
            artist: "Boards of Canada",
            vote_count: 1,
          }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /^winners$/i });
      const section = sectionFor(/^winners$/i);
      expect(within(section).getByText("tied for the most votes this round")).toBeInTheDocument();
      expect(within(section).getByText("Bad Guy")).toBeInTheDocument();
      expect(within(section).getByText("Vienna")).toBeInTheDocument();
      // the lower-voted song is not co-recognized
      expect(within(section).queryByText("Roygbiv")).not.toBeInTheDocument();
    });

    it("Winner: section is omitted when no song drew a vote", async () => {
      setupClosed({ submissions: [sub({ title: "Bad Guy", vote_count: 0 })] });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      expect(screen.queryByRole("heading", { name: /^winner$/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /^winners$/i })).not.toBeInTheDocument();
    });

    // ----- Leaderboard ----------------------------------------------------- //

    it("Leaderboard: renders entries in order with rank, name, and vote count", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "s1", user_id: "u-bo", title: "Bad Guy", vote_count: 3 }),
          sub({
            submission_id: "s2",
            user_id: "u-cal",
            submitter_display_name: "Cal",
            title: "Vienna",
            artist: "Billy Joel",
            vote_count: 1,
          }),
        ],
        leaderboard: [
          { user_id: "u-bo", display_name: "Bo", vote_count: 3, rank: 1 },
          { user_id: "u-cal", display_name: "Cal", vote_count: 1, rank: 2 },
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /leaderboard/i });
      const section = sectionFor(/leaderboard/i);
      const rows = within(section).getAllByRole("listitem");
      expect(rows).toHaveLength(2);
      // order: rank 1 then rank 2
      expect(within(rows[0]).getByText("1")).toBeInTheDocument();
      expect(within(rows[0]).getByText("Bo")).toBeInTheDocument();
      expect(within(rows[0]).getByText("3 votes")).toBeInTheDocument();
      expect(within(rows[1]).getByText("2")).toBeInTheDocument();
      expect(within(rows[1]).getByText("Cal")).toBeInTheDocument();
      expect(within(rows[1]).getByText("1 vote")).toBeInTheDocument();
    });

    it("Leaderboard: a vibing submitter (absent from leaderboard) does not appear in it", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "s1", user_id: "u-bo", title: "Bad Guy", vote_count: 2 }),
          sub({
            submission_id: "s2",
            user_id: "u-vee",
            submitter_display_name: "Vee",
            title: "Ambient Drift",
            artist: "Brian Eno",
            participation_mode: "vibing",
            vote_count: 0,
          }),
        ],
        leaderboard: [{ user_id: "u-bo", display_name: "Bo", vote_count: 2, rank: 1 }],
      });
      renderRound();

      await screen.findByRole("heading", { name: /leaderboard/i });
      const section = sectionFor(/leaderboard/i);
      expect(within(section).getByText("Bo")).toBeInTheDocument();
      // the vibing submitter is in the picks but NOT on the leaderboard
      expect(within(section).queryByText("Vee")).not.toBeInTheDocument();
      expect(within(section).getAllByRole("listitem")).toHaveLength(1);
    });

    it("Leaderboard: section is omitted when there are no ranked players", async () => {
      setupClosed({
        submissions: [sub({ participation_mode: "vibing", vote_count: 0 })],
        leaderboard: [],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      expect(screen.queryByRole("heading", { name: /leaderboard/i })).not.toBeInTheDocument();
    });

    // ----- Submissions ----------------------------------------------------- //

    it("Submissions: shows submitter name, vote count, the submitter note in quotes, and others' notes", async () => {
      setupClosed({
        submissions: [
          sub({
            submission_id: "s1",
            user_id: OTHER,
            submitter_display_name: "Bob",
            title: "Bad Guy",
            artist: "Billie Eilish",
            participation_mode: "playing",
            submitter_note: "a banger",
            vote_count: 2,
            notes: [{ body: "this slaps", author_display_name: "Ada", created_at: "x" }],
          }),
        ],
      });
      renderRound();

      const user = userEvent.setup();
      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      expect(within(card).getByText("Bob")).toBeInTheDocument();
      expect(within(card).getByText("2 votes")).toBeInTheDocument();
      // submitter note is rendered in curly quotes
      expect(within(card).getByText(/a banger/)).toBeInTheDocument();
      expect(within(card).getByText(/“a banger”/)).toBeInTheDocument();
      // others' notes are collapsed by default — expand to read them
      await user.click(within(card).getByRole("button", { name: /show 1 note/i }));
      expect(within(card).getByText("this slaps")).toBeInTheDocument();
      expect(within(card).getByText("Ada")).toBeInTheDocument();
    });

    it("Submissions: notes are collapsed by default and toggle open/closed (MYS-72)", async () => {
      const user = userEvent.setup();
      setupClosed({
        submissions: [
          sub({
            title: "Bad Guy",
            vote_count: 1,
            notes: [
              { body: "this slaps", author_display_name: "Ada", created_at: "x" },
              { body: "on repeat", author_display_name: "Cal", created_at: "y" },
            ],
          }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      // collapsed by default: bodies hidden behind a "show N notes" toggle
      expect(within(card).queryByText("this slaps")).not.toBeInTheDocument();
      expect(within(card).getByRole("button", { name: /show 2 notes/i })).toHaveAttribute(
        "aria-expanded",
        "false",
      );

      await user.click(within(card).getByRole("button", { name: /show 2 notes/i }));
      expect(within(card).getByText("this slaps")).toBeInTheDocument();
      expect(within(card).getByText("on repeat")).toBeInTheDocument();

      // collapses again
      await user.click(within(card).getByRole("button", { name: /hide 2 notes/i }));
      expect(within(card).queryByText("this slaps")).not.toBeInTheDocument();
    });

    it("Submissions: the caller's own submission is labelled 'you'", async () => {
      setupClosed({
        submissions: [
          sub({
            submission_id: "s1",
            user_id: ORGANIZER, // the authed user (setAuth(ORGANIZER) in beforeEach)
            submitter_display_name: "Bob",
            title: "Bad Guy",
            vote_count: 1,
          }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      expect(within(card).getByText("you")).toBeInTheDocument();
      // their real display name is not shown for their own pick
      expect(within(card).queryByText("Bob")).not.toBeInTheDocument();
    });

    it("Submissions: a single-vote pick reads '1 vote' (singular)", async () => {
      setupClosed({
        submissions: [sub({ title: "Bad Guy", participation_mode: "playing", vote_count: 1 })],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      expect(within(card).getByText("1 vote")).toBeInTheDocument();
    });

    it("Submissions: a vibing pick shows the 'just vibing' badge and NO vote count", async () => {
      setupClosed({
        submissions: [
          sub({
            submission_id: "v1",
            title: "Ambient Drift",
            artist: "Brian Eno",
            participation_mode: "vibing",
            vote_count: 0,
          }),
        ],
      });
      renderRound();

      await screen.findByText("Ambient Drift");
      const card = cardFor("Ambient Drift");
      expect(within(card).getByText(/just vibing/i)).toBeInTheDocument();
      // no score rendered for a vibing pick
      expect(within(card).queryByText(/\bvotes?\b/i)).not.toBeInTheDocument();
      expect(within(card).queryByText("0 votes")).not.toBeInTheDocument();
    });

    it("Submissions: a pick with no submitter note and no notes renders neither", async () => {
      setupClosed({
        submissions: [sub({ title: "Bad Guy", submitter_note: null, notes: [], vote_count: 4 })],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      // no curly-quoted note, no note authors
      expect(within(card).queryByText(/“/)).not.toBeInTheDocument();
      expect(within(card).getByText("4 votes")).toBeInTheDocument();
    });

    it("empty results (no submissions) shows the empty state", async () => {
      setupClosed({ submissions: [], leaderboard: [], most_noted: { note_count: 0, winners: [] } });
      renderRound();

      expect(await screen.findByText(/no submissions/i)).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: /the picks/i })).not.toBeInTheDocument();
    });

    // ----- Data loading ---------------------------------------------------- //

    it("calls getResults for a closed round and not the old submissions/members loaders", async () => {
      setupClosed({ submissions: [sub({ title: "Bad Guy" })] });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      expect(mockGetResults).toHaveBeenCalledWith("r1");
      // closed view no longer uses these
      expect(mockGetPlaylist).not.toHaveBeenCalled();
      expect(mockGetMine).not.toHaveBeenCalled();
    });

    it("when getResults rejects with an ApiError, the page shows its error state", async () => {
      const { ApiError } =
        await vi.importActual<typeof import("../services/api")>("../services/api");
      mockGetRound.mockResolvedValue(round({ state: "closed" }));
      mockGetResults.mockRejectedValue(new ApiError(409, "results are available once it closes"));
      renderRound();

      expect(await screen.findByText(/results are available once it closes/i)).toBeInTheDocument();
      // nothing rendered for the picks
      expect(screen.queryByRole("heading", { name: /the picks/i })).not.toBeInTheDocument();
    });
  });
});
