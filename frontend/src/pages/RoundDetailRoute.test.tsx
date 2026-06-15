import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RoundDetailRoute } from "./RoundDetailRoute";
import {
  getLeague,
  getLeagueMembers,
  getMySubmission,
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
});
