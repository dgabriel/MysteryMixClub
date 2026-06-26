import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RoundDetailRoute } from "./RoundDetailRoute";
import {
  addNote,
  castVotes,
  getLeague,
  getMyMembership,
  getMySubmission,
  getMyVotes,
  getNotes,
  getPlaylist,
  getResults,
  getRound,
  getSpotifyStatus,
  resolveSong,
  submitSong,
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
    getMyMembership: vi.fn(),
    getMySubmission: vi.fn(),
    getPlaylist: vi.fn(),
    getResults: vi.fn(),
    updateRound: vi.fn(),
    submitSong: vi.fn(),
    resolveSong: vi.fn(),
    getMyVotes: vi.fn(),
    castVotes: vi.fn(),
    getNotes: vi.fn(),
    addNote: vi.fn(),
    getSpotifyStatus: vi.fn(),
  };
});
vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetRound = vi.mocked(getRound);
const mockGetLeague = vi.mocked(getLeague);
const mockGetMyMembership = vi.mocked(getMyMembership);
const mockGetMine = vi.mocked(getMySubmission);
const mockGetPlaylist = vi.mocked(getPlaylist);
const mockGetResults = vi.mocked(getResults);
const mockUpdateRound = vi.mocked(updateRound);
const mockGetMyVotes = vi.mocked(getMyVotes);
const mockCastVotes = vi.mocked(castVotes);
const mockGetNotes = vi.mocked(getNotes);
const mockAddNote = vi.mocked(addNote);
const mockGetSpotifyStatus = vi.mocked(getSpotifyStatus);
const mockResolveSong = vi.mocked(resolveSong);
const mockSubmitSong = vi.mocked(submitSong);
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
    submission_count: 0,
    member_count: 0,
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
    default_vibe_mode: false,
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
    viewer_is_vibing: false,
    winners: [],
    picks: [],
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
    email: "x@example.com",
    userId,
    profileStatus: "ready",
    needsOnboarding: false,
    isPlatformAdmin: false,
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
    mockGetMyMembership.mockResolvedValue({
      league_id: "lg1",
      user_id: ORGANIZER,
      vibe_mode: false,
    });
    mockGetMine.mockResolvedValue(null);
    // Spotify feature hidden by default in these tests (not configured).
    mockGetSpotifyStatus.mockResolvedValue({ configured: false, connected: false });
    mockGetPlaylist.mockResolvedValue({
      round_id: "r1",
      round_number: 1,
      theme: "t",
      state: "open_voting",
      entries: [],
      youtube_playlist_url: null,
      youtube_track_count: 0,
      voting_eligible: 0,
      voting_acted: 0,
      vibing_count: 0,
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

  it("open_submission: shows submission progress (X of Y submitted) — MYS-101", async () => {
    mockGetRound.mockResolvedValue(round({ submission_count: 2, member_count: 5 }));
    renderRound();
    expect(await screen.findByText("2 of 5 submitted")).toBeInTheDocument();
  });

  it("open_submission: hides progress until the member count is known — MYS-101", async () => {
    mockGetRound.mockResolvedValue(round({ submission_count: 0, member_count: 0 }));
    renderRound();
    // Wait for the screen to settle on the submit card, then assert no progress.
    expect(await screen.findByRole("heading", { name: /submit a song/i })).toBeInTheDocument();
    expect(screen.queryByText(/submitted$/i)).not.toBeInTheDocument();
  });

  it("open_submission: round vibe toggle seeds from membership and submit sends participation_mode (MYS-60)", async () => {
    const user = userEvent.setup();
    mockGetMyMembership.mockResolvedValue({
      league_id: "lg1",
      user_id: ORGANIZER,
      vibe_mode: true,
    });
    mockResolveSong.mockResolvedValue({
      title: "Debaser",
      artist: "Pixies",
      isrc: "I1",
      album: null,
      thumbnail_url: null,
      platforms: {},
    } as Awaited<ReturnType<typeof resolveSong>>);
    mockSubmitSong.mockResolvedValue(mine({ participation_mode: "vibing" }));

    renderRound();

    // Seeded checked from the member's per-league vibe_mode.
    const toggle = await screen.findByLabelText(/just vibes for this round/i);
    expect(toggle).toBeChecked();

    await user.type(screen.getByLabelText(/paste a spotify or youtube link/i), "https://x");
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));
    await user.click(await screen.findByRole("button", { name: /submit this song/i }));

    expect(mockSubmitSong).toHaveBeenCalledWith(
      "r1",
      expect.objectContaining({ participation_mode: "vibing" }),
    );
  });

  it("open_submission: submitting a song refreshes the X of Y count — MYS-101", async () => {
    const user = userEvent.setup();
    // The round is refetched after a successful submit: first load shows 0, the
    // post-submit refetch shows 1.
    mockGetRound
      .mockResolvedValueOnce(round({ submission_count: 0, member_count: 5 }))
      .mockResolvedValue(round({ submission_count: 1, member_count: 5 }));
    mockResolveSong.mockResolvedValue({
      title: "Debaser",
      artist: "Pixies",
      isrc: "I1",
      album: null,
      thumbnail_url: null,
      platforms: {},
    } as Awaited<ReturnType<typeof resolveSong>>);
    mockSubmitSong.mockResolvedValue({
      id: "s1",
      round_id: "r1",
      user_id: ORGANIZER,
      isrc: "I1",
      title: "Debaser",
      artist: "Pixies",
      album: null,
      album_art_url: null,
      note: null,
      participation_mode: "playing",
      created_at: "2026-01-01T00:00:00Z",
    });

    renderRound();
    expect(await screen.findByText("0 of 5 submitted")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/paste a spotify or youtube link/i), "https://x");
    await user.click(screen.getByRole("button", { name: /^resolve$/i }));
    await user.click(await screen.findByRole("button", { name: /submit this song/i }));

    expect(await screen.findByText("1 of 5 submitted")).toBeInTheDocument();
    expect(mockSubmitSong).toHaveBeenCalledTimes(1);
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

  it("advance button resets after a successful open (not stuck on 'opening…') — MYS-95", async () => {
    const user = userEvent.setup();
    renderRound();
    await user.click(await screen.findByRole("button", { name: /open voting/i }));
    expect(mockUpdateRound).toHaveBeenCalled();
    // After success the button returns to its label; it must not stay "opening…".
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /open voting/i })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /opening/i })).not.toBeInTheDocument();
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
      voting_eligible: 0,
      voting_acted: 0,
      vibing_count: 0,
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
            platforms: {},
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
      votingEligible?: number;
      votingActed?: number;
      vibingCount?: number;
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
        voting_eligible: opts.votingEligible ?? 0,
        voting_acted: opts.votingActed ?? 0,
        vibing_count: opts.vibingCount ?? 0,
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

    it("voting progress: shows X of Y voted or noted · Z just vibing (MYS-102)", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
        votingEligible: 4,
        votingActed: 2,
        vibingCount: 1,
      });
      renderRound();

      expect(await screen.findByText("2 of 4 voted or noted · 1 just vibing")).toBeInTheDocument();
    });

    it("voting progress: omits the vibing clause when nobody is vibing (MYS-102)", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
        votingEligible: 3,
        votingActed: 1,
        vibingCount: 0,
      });
      renderRound();

      expect(await screen.findByText("1 of 3 voted or noted")).toBeInTheDocument();
      expect(screen.queryByText(/just vibing/i)).not.toBeInTheDocument();
    });

    it("voting progress: refreshes after casting votes (MYS-102)", async () => {
      const user = userEvent.setup();
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        myVotes: [],
        votingEligible: 4,
        votingActed: 1,
        vibingCount: 0,
      });
      // Key the reported progress on whether a cast has happened, so the
      // assertion is robust to how many times the playlist is (re)fetched: the
      // caller joins the "acted" tally only after they cast (1 → 2 of 4).
      let casted = false;
      mockCastVotes.mockImplementation(async () => {
        casted = true;
        return { round_id: "r1", submission_ids: ["p1"], count: 1, votes_per_player: 3 };
      });
      mockGetPlaylist.mockImplementation(async () => ({
        round_id: "r1",
        round_number: 1,
        theme: "t",
        state: "open_voting",
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Hey" }),
        ],
        youtube_playlist_url: null,
        youtube_track_count: 0,
        voting_eligible: 4,
        voting_acted: casted ? 2 : 1,
        vibing_count: 0,
      }));
      renderRound();

      expect(await screen.findByText("1 of 4 voted or noted")).toBeInTheDocument();
      await user.click(await screen.findByRole("button", { name: /Debaser/i }));
      await user.click(screen.getByRole("button", { name: /cast votes/i }));

      expect(await screen.findByText("2 of 4 voted or noted")).toBeInTheDocument();
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

    it("every submission is a votable toggle — no separate vibing section (MYS-112)", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Ambient Drift" }),
        ],
        myVotes: [],
      });
      renderRound();

      // Every song is a votable toggle now — vibing is private during voting.
      expect(await screen.findByRole("button", { name: /Debaser/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Ambient Drift/i })).toBeInTheDocument();
      // No separate "just vibing" section or "along for the ride" copy.
      expect(screen.queryByRole("heading", { name: /just vibing/i })).not.toBeInTheDocument();
      expect(screen.queryByText(/along for the ride/i)).not.toBeInTheDocument();
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

    it("vibing viewer can leave a note on each song (MYS-132)", async () => {
      setupVoting({
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        myVotes: [],
        mine: mine({ participation_mode: "vibing" }),
      });
      renderRound();

      // Vibers don't vote, but they can still leave notes — the affordance is
      // present on the playlist card.
      expect(await screen.findByText(/you sit voting out/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /leave a note/i })).toBeInTheDocument();
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
      voting_eligible: 0,
      voting_acted: 0,
      vibing_count: 0,
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

    it("a song that's vibing for its submitter is a normal votable card to others (MYS-112)", async () => {
      setupVoting({
        entries: [
          entry({ submission_id: "p1", title: "Debaser" }),
          entry({ submission_id: "p2", title: "Ambient Drift" }),
        ],
      });
      renderRound();

      // It's a votable toggle like any other, and the old vibing-only
      // "can't vote on this one — leave a note instead" hint is gone entirely.
      expect(await screen.findByRole("button", { name: /Ambient Drift/i })).toBeInTheDocument();
      expect(screen.queryByText(/can't vote on this one/i)).not.toBeInTheDocument();
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
              platforms: {},
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
        platforms: {},
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

    // ----- Vibing-viewer reveal (MYS-112 / MYS-134) ------------------------ //

    it("vibing viewer: winner + full tracklist with notes, no leaderboard or scores", async () => {
      setupClosed({
        viewer_is_vibing: true,
        submissions: [],
        leaderboard: [],
        winners: [
          {
            submission_id: "w1",
            title: "Winning Song",
            artist: "The Champs",
            submitter_display_name: "Wren",
          },
        ],
        picks: [
          {
            submission_id: "w1",
            submitter_display_name: "Wren",
            title: "Winning Song",
            artist: "The Champs",
            platforms: {},
            submitter_note: null,
            notes: [],
          },
          {
            submission_id: "mine",
            submitter_display_name: "Vera",
            title: "My Quiet Pick",
            artist: "Me",
            platforms: { spotify: "https://open.spotify.com/track/x" },
            submitter_note: null,
            notes: [{ body: "this one got me", author_display_name: "Ada", created_at: "x" }],
          },
        ],
      });
      renderRound();

      // Winner named (no count) and the full tracklist is visible, with notes
      // behind the collapsible toggle. "Winning Song" shows in both the winner
      // highlight and the tracklist.
      expect(await screen.findByRole("heading", { name: /the picks/i })).toBeInTheDocument();
      expect(screen.getAllByText("Winning Song").length).toBeGreaterThanOrEqual(2);
      expect(screen.getByText("My Quiet Pick")).toBeInTheDocument();
      // The tracklist tiles are playable (regression — MYS-134 tiles need links).
      expect(screen.getByRole("link", { name: /on Spotify/i })).toBeInTheDocument();
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: /show 1 note/i }));
      expect(screen.getByText("this one got me")).toBeInTheDocument();
      // No leaderboard and no vote tallies for a viber.
      expect(screen.queryByRole("heading", { name: /leaderboard/i })).not.toBeInTheDocument();
      expect(screen.queryByText(/\bvotes?\b/i)).not.toBeInTheDocument();
    });

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
        submissions: [sub({ vote_count: 0 })],
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
        submissions: [sub({ title: "Bad Guy", vote_count: 1 })],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      expect(within(card).getByText("1 vote")).toBeInTheDocument();
    });

    it("Submissions: a pick tile shows per-song platform links (regression)", async () => {
      setupClosed({
        submissions: [
          sub({
            title: "Bad Guy",
            platforms: { spotify: "https://open.spotify.com/track/x" },
          }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      const card = cardFor("Bad Guy");
      const link = within(card).getByRole("link", { name: /on Spotify/i });
      expect(link).toHaveAttribute("href", "https://open.spotify.com/track/x");
    });

    it("Submissions: every pick shows its vote count and no vibing badge (MYS-112)", async () => {
      setupClosed({
        submissions: [
          sub({ submission_id: "w1", title: "Top Song", artist: "A", vote_count: 5 }),
          sub({ submission_id: "v1", title: "Ambient Drift", artist: "Brian Eno", vote_count: 1 }),
        ],
      });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      // "Ambient Drift" isn't the winner, so it only appears in the picks list.
      const card = cardFor("Ambient Drift");
      // The reveal never shows who vibed — just the score, like any other pick.
      expect(within(card).getByText("1 vote")).toBeInTheDocument();
      expect(within(card).queryByText(/just vibing/i)).not.toBeInTheDocument();
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

    it("closed round shows a 'listen back' affordance when there are tracks (MYS-133)", async () => {
      mockGetPlaylist.mockResolvedValue({
        round_id: "r1",
        round_number: 1,
        theme: "t",
        state: "closed",
        entries: [entry({ submission_id: "p1", title: "Debaser" })],
        youtube_playlist_url: "https://www.youtube.com/watch_videos?video_ids=a",
        youtube_track_count: 1,
        voting_eligible: 0,
        voting_acted: 0,
        vibing_count: 0,
      });
      setupClosed({ submissions: [sub({ title: "Debaser" })] });
      renderRound();

      expect(await screen.findByRole("heading", { name: /listen back/i })).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: /open playlist in youtube/i }),
      ).toBeInTheDocument();
    });

    it("calls getResults + getPlaylist for a closed round, and not getMine", async () => {
      setupClosed({ submissions: [sub({ title: "Bad Guy" })] });
      renderRound();

      await screen.findByRole("heading", { name: /the picks/i });
      expect(mockGetResults).toHaveBeenCalledWith("r1");
      // The closed view also pulls the playlist for the "listen back" affordance
      // (MYS-133), but never the caller's own submission.
      expect(mockGetPlaylist).toHaveBeenCalledWith("r1");
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
