import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { SubmissionHistoryRoute } from "./SubmissionHistoryRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, getMySubmissionHistory } from "../services/api";
import type { MySubmission } from "../services/api";
import { useAuth } from "../hooks/useAuth";

vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getMySubmissionHistory: vi.fn(),
  };
});

vi.mock("../hooks/useAuth", () => ({ useAuth: vi.fn() }));

const mockGetMySubmissionHistory = vi.mocked(getMySubmissionHistory);
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

function entryWith(overrides: Partial<MySubmission> = {}): MySubmission {
  return {
    submission_id: "sub-1",
    club_id: "club-1",
    club_name: "Friday Mixtape",
    mix_id: "mix-1",
    mix_number: 1,
    theme: "road trip",
    state: "closed",
    isrc: "USABC1234567",
    source: null,
    source_url: null,
    title: "Song One",
    artist: "Artist One",
    album: null,
    album_art_url: null,
    submitter_note: null,
    notes: [],
    vote_count: null,
    voters: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderHistory() {
  return render(
    <MemoryRouter initialEntries={["/profile/history"]}>
      <Routes>
        <Route element={<AuthedLayout />}>
          <Route path="/profile/history" element={<SubmissionHistoryRoute />} />
        </Route>
        <Route path="/mixes/:id" element={<div>MIX DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The row toggle's accessible name is on the chevron button, keyed off the
 *  song title (see SubmissionHistoryScreen's `aria-label`). */
function rowToggle(title: string) {
  return screen.getByRole("button", { name: new RegExp(`(show|hide) details for ${title}`, "i") });
}

describe("SubmissionHistoryRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setAuth();
  });

  it("shows an empty state when the caller has never submitted anything", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([]);

    renderHistory();

    expect(await screen.findByText(/haven't submitted a song yet/i)).toBeInTheDocument();
  });

  it("renders each submission as a grid row with club, mix, date, vote and note counts", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        title: "Song One",
        artist: "Artist One",
        club_name: "Friday Mixtape",
        mix_number: 3,
        created_at: "2026-03-05T00:00:00Z",
        vote_count: 4,
        notes: [{ body: "nice", author_display_name: "Sam", created_at: "2026-03-06T00:00:00Z" }],
      }),
    ]);

    renderHistory();

    const row = (await screen.findByText("Song One")).closest("tr");
    expect(row).not.toBeNull();
    // ClubName splits a multi-word name across text nodes (its second word is
    // its own <span>), so check each word rather than the joined string.
    expect(screen.getByText(/friday/i)).toBeInTheDocument();
    expect(screen.getByText(/mixtape/i)).toBeInTheDocument();
    expect(screen.getByText("Artist One")).toBeInTheDocument();
    const expectedDate = new Date("2026-03-05T00:00:00Z").toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
    expect(screen.getByText(expectedDate)).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // mix number
    expect(screen.getByText("4")).toBeInTheDocument(); // vote count
    expect(screen.getByText("1")).toBeInTheDocument(); // note count
    // The theme is in the collapsed-by-default preview, not the row itself.
    expect(screen.queryByText(/road trip/i)).not.toBeInTheDocument();
  });

  it("keeps the preview collapsed until the row is toggled open", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        theme: "road trip",
        submitter_note: "my pick",
        notes: [{ body: "great pick", author_display_name: "Sam", created_at: "2026-01-02T00:00:00Z" }],
      }),
    ]);

    renderHistory();
    await screen.findByText("Song One");

    const toggle = rowToggle("Song One");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("great pick")).not.toBeInTheDocument();
    expect(screen.queryByText(/road trip/i)).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("great pick")).toBeInTheDocument();
    expect(screen.getByText(/road trip/i)).toBeInTheDocument();
    expect(screen.getByText(/my pick/i)).toBeInTheDocument();
  });

  it("toggles the preview when the row itself is clicked, not just the chevron", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith({ submitter_note: "my pick" })]);

    renderHistory();
    const cell = await screen.findByText("Song One");

    await userEvent.click(cell);

    expect(rowToggle("Song One")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/my pick/i)).toBeInTheDocument();
  });

  it("hides vote identity for a still-open mix and shows it once closed", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        submission_id: "open-sub",
        title: "Open Song",
        state: "open_voting",
        vote_count: null,
        voters: [],
      }),
      entryWith({
        submission_id: "closed-sub",
        title: "Closed Song",
        state: "closed",
        vote_count: 2,
        voters: [{ user_id: "voter-1", display_name: "Sam", weight: 2 }],
      }),
    ]);

    renderHistory();
    await screen.findByText("Open Song");

    // Grid cell shows "hidden" rather than a number for the open mix.
    expect(screen.getByText("hidden")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();

    await userEvent.click(rowToggle("Open Song"));
    expect(screen.getByText(/votes reveal once this mix closes/i)).toBeInTheDocument();

    await userEvent.click(rowToggle("Closed Song"));
    expect(screen.getByText(/voted by sam ×2/i)).toBeInTheDocument();
  });

  it("filters by title/artist search", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Blue Moon", artist: "Sinatra" }),
      entryWith({ submission_id: "s2", title: "Purple Rain", artist: "Prince" }),
    ]);

    renderHistory();
    await screen.findByText("Blue Moon");

    await userEvent.type(screen.getByLabelText(/search/i), "prince");

    expect(screen.queryByText("Blue Moon")).not.toBeInTheDocument();
    expect(screen.getByText("Purple Rain")).toBeInTheDocument();
  });

  it("sorts by clicking the song column header", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Zebra", artist: "Z" }),
      entryWith({ submission_id: "s2", title: "Apple", artist: "A" }),
    ]);

    renderHistory();
    await screen.findByText("Zebra");

    await userEvent.click(screen.getByRole("button", { name: "song" }));

    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    const titles = rows.map((r) => r.textContent);
    expect(titles[0]).toContain("Apple");
    expect(titles[1]).toContain("Zebra");
  });

  it("navigates to the mix from the expanded preview's link", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith({ mix_id: "mix-42" })]);

    renderHistory();
    await screen.findByText("Song One");
    await userEvent.click(rowToggle("Song One"));
    await userEvent.click(screen.getByRole("button", { name: /open mix/i }));

    expect(await screen.findByText("MIX DETAIL CONTENT")).toBeInTheDocument();
  });

  it("shows the server's error message when the load fails", async () => {
    mockGetMySubmissionHistory.mockRejectedValue(new ApiError(500, "server error"));

    renderHistory();

    // Mirrors ProfileRoute's pattern: an ApiError's own message passes
    // through verbatim; the generic fallback is only for a non-ApiError throw.
    expect(await screen.findByRole("alert")).toHaveTextContent("server error");
  });
});
