import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { ClubSongsRoute } from "./ClubSongsRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, getClub, getClubSongs } from "../services/api";
import type { Club, ClubSong } from "../services/api";
import { useAuth } from "../hooks/useAuth";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getClub: vi.fn(),
    getClubSongs: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetClub = vi.mocked(getClub);
const mockGetClubSongs = vi.mocked(getClubSongs);
const mockUseAuth = vi.mocked(useAuth);

function setAuth() {
  mockUseAuth.mockReturnValue({
    status: "authenticated",
    isAuthenticated: true,
    setAccessToken: vi.fn(),
    clear: vi.fn(),
    logout: vi.fn(),
    logoutAll: vi.fn(),
    displayName: "Ada",
    email: "ada@example.com",
    userId: "user-1",
    isPlatformAdmin: false,
    profileStatus: "ready",
    needsOnboarding: false,
    applyDisplayName: vi.fn(),
    preferredService: null,
    tosAccepted: true,
    applyTosAccepted: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function clubWith(overrides: Partial<Club> = {}): Club {
  return {
    id: "club-1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "org-1",
    total_mixes: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_mix: 6,
    state: "active",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    deadline_mode: "duration",
    timezone: "UTC",
    submission_weekday: null,
    submission_time: null,
    voting_weekday: null,
    voting_time: null,
    created_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    viewer_is_admin: null,
    ...overrides,
  };
}

function entryWith(overrides: Partial<ClubSong> = {}): ClubSong {
  return {
    submission_id: "sub-1",
    user_id: "user-2",
    submitter_display_name: "Sam",
    mix_id: "mix-1",
    mix_number: 1,
    theme: "road trip",
    isrc: "USABC1234567",
    source: null,
    source_url: null,
    title: "Song One",
    artist: "Artist One",
    album: null,
    album_art_url: null,
    submitter_note: null,
    notes: [],
    vote_count: 0,
    voters: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderClubSongs() {
  return render(
    <MemoryRouter initialEntries={["/clubs/club-1/songs"]}>
      <Routes>
        <Route element={<AuthedLayout />}>
          <Route path="/clubs/:id/songs" element={<ClubSongsRoute />} />
        </Route>
        <Route path="/mixes/:id" element={<div>MIX DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

function rowToggle(title: string) {
  return screen.getByRole("button", { name: new RegExp(`(show|hide) details for ${title}`, "i") });
}

describe("ClubSongsRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth();
    mockGetClub.mockResolvedValue(clubWith());
  });

  it("shows an empty state when the club has no closed-mix submissions yet", async () => {
    mockGetClubSongs.mockResolvedValue([]);

    renderClubSongs();

    expect(await screen.findByText(/no songs yet/i)).toBeInTheDocument();
  });

  it("renders the club name in the heading and each song as a grid row", async () => {
    mockGetClubSongs.mockResolvedValue([
      entryWith({
        title: "Song One",
        artist: "Artist One",
        submitter_display_name: "Sam",
        mix_number: 4,
        vote_count: 3,
        notes: [{ body: "nice", author_display_name: "Bo", created_at: "2026-01-02T00:00:00Z" }],
      }),
    ]);

    renderClubSongs();

    expect(await screen.findByRole("heading", { name: /friday mixtape/i })).toBeInTheDocument();
    expect(screen.getByText("Song One")).toBeInTheDocument();
    expect(screen.getByText("Artist One")).toBeInTheDocument();
    expect(screen.getByText("Sam")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument(); // mix number
    expect(screen.getByText("3")).toBeInTheDocument(); // vote count
    expect(screen.getByText("1")).toBeInTheDocument(); // note count
    // Theme is in the collapsed-by-default preview, not the row itself.
    expect(screen.queryByText(/road trip/i)).not.toBeInTheDocument();
  });

  it("reveals voters and notes in full once expanded (no anonymity gating -- mix is always closed)", async () => {
    mockGetClubSongs.mockResolvedValue([
      entryWith({
        theme: "road trip",
        submitter_note: "my pick",
        voters: [{ user_id: "v1", display_name: "Bo", weight: 2 }],
        notes: [{ body: "great pick", author_display_name: "Bo", created_at: "2026-01-02T00:00:00Z" }],
      }),
    ]);

    renderClubSongs();
    await screen.findByText("Song One");

    const toggle = rowToggle("Song One");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("great pick")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(screen.getByText(/road trip/i)).toBeInTheDocument();
    expect(screen.getByText(/my pick/i)).toBeInTheDocument();
    expect(screen.getByText(/voted by bo ×2/i)).toBeInTheDocument();
    expect(screen.getByText("great pick")).toBeInTheDocument();
  });

  it("filters by title/artist search", async () => {
    mockGetClubSongs.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Blue Moon", artist: "Sinatra" }),
      entryWith({ submission_id: "s2", title: "Purple Rain", artist: "Prince" }),
    ]);

    renderClubSongs();
    await screen.findByText("Blue Moon");

    await userEvent.type(screen.getByLabelText(/search/i), "prince");

    expect(screen.queryByText("Blue Moon")).not.toBeInTheDocument();
    expect(screen.getByText("Purple Rain")).toBeInTheDocument();
  });

  it("sorts by clicking the submitter column header", async () => {
    mockGetClubSongs.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Zebra", submitter_display_name: "Zed" }),
      entryWith({ submission_id: "s2", title: "Apple", submitter_display_name: "Ann" }),
    ]);

    renderClubSongs();
    await screen.findByText("Zebra");

    await userEvent.click(screen.getByRole("button", { name: "submitter" }));

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows[0].textContent).toContain("Apple");
    expect(rows[1].textContent).toContain("Zebra");
  });

  it("navigates to the mix from the expanded preview's link", async () => {
    mockGetClubSongs.mockResolvedValue([entryWith({ mix_id: "mix-42" })]);

    renderClubSongs();
    await screen.findByText("Song One");
    await userEvent.click(rowToggle("Song One"));
    await userEvent.click(screen.getByRole("button", { name: /open mix/i }));

    expect(await screen.findByText("MIX DETAIL CONTENT")).toBeInTheDocument();
  });

  it("paginates once there are more than 25 songs, and resets to page 1 on search", async () => {
    const entries = Array.from({ length: 30 }, (_, i) =>
      entryWith({
        submission_id: `s${i}`,
        title: `Song ${String(i).padStart(2, "0")}`,
        artist: "Artist",
      }),
    );
    mockGetClubSongs.mockResolvedValue(entries);

    renderClubSongs();
    await screen.findByText("Song 00");

    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
    expect(screen.queryByText("Song 25")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /prev/i })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    expect(await screen.findByText("Song 25")).toBeInTheDocument();
    expect(screen.queryByText("Song 00")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

    // Typing a search (even one that matches everything) should snap back to
    // page 1 -- otherwise a search from page 2 could render an empty grid if
    // the new result set has fewer pages than the one being viewed.
    await userEvent.type(screen.getByLabelText(/search/i), "Song");

    expect(await screen.findByText("Song 00")).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
  });

  it("has no pagination control when everything fits on one page", async () => {
    mockGetClubSongs.mockResolvedValue([entryWith()]);

    renderClubSongs();
    await screen.findByText("Song One");

    expect(screen.queryByRole("navigation", { name: /pagination/i })).not.toBeInTheDocument();
  });

  it("shows the server's error message when the load fails", async () => {
    mockGetClubSongs.mockRejectedValue(new ApiError(500, "server error"));

    renderClubSongs();

    expect(await screen.findByRole("alert")).toHaveTextContent("server error");
  });
});
