import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
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
 *  song title (see SubmissionHistoryScreen's `aria-label`). The mobile card's
 *  own toggle button shares that same accessible name (MysteryMixClub-4vii.7),
 *  so this is scoped to the desktop table to stay unambiguous. */
function rowToggle(title: string) {
  return within(screen.getByRole("table")).getByRole("button", {
    name: new RegExp(`(show|hide) details for ${title}`, "i"),
  });
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
        notes: [
          {
            id: "note-1",
            author_id: "user-sam",
            body: "nice",
            author_display_name: "Sam",
            created_at: "2026-03-06T00:00:00Z",
          },
        ],
      }),
    ]);

    renderHistory();

    // The mobile card list mirrors the same fields (MysteryMixClub-4vii.7),
    // so title/club/artist/date text is ambiguous unscoped -- pin these
    // checks to the desktop table.
    const table = await screen.findByRole("table");
    const row = within(table).getByText("Song One").closest("tr");
    expect(row).not.toBeNull();
    // ClubName splits a multi-word name across text nodes (its second word is
    // its own <span>), so check each word rather than the joined string.
    expect(within(table).getByText(/friday/i)).toBeInTheDocument();
    expect(within(table).getByText(/mixtape/i)).toBeInTheDocument();
    expect(within(table).getByText("Artist One")).toBeInTheDocument();
    const expectedDate = new Date("2026-03-05T00:00:00Z").toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
    expect(within(table).getByText(expectedDate)).toBeInTheDocument();
    expect(within(table).getByText("3")).toBeInTheDocument(); // mix number
    expect(within(table).getByText("4")).toBeInTheDocument(); // vote count
    expect(within(table).getByText("1")).toBeInTheDocument(); // note count
    // The theme is in the collapsed-by-default preview, not the row itself.
    expect(screen.queryByText(/road trip/i)).not.toBeInTheDocument();
  });

  it("keeps the preview collapsed until the row is toggled open", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        theme: "road trip",
        submitter_note: "my pick",
        notes: [
          {
            id: "note-2",
            author_id: "user-sam",
            body: "great pick",
            author_display_name: "Sam",
            created_at: "2026-01-02T00:00:00Z",
          },
        ],
      }),
    ]);

    renderHistory();
    const table = await screen.findByRole("table");

    const toggle = rowToggle("Song One");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("great pick")).not.toBeInTheDocument();
    expect(screen.queryByText(/road trip/i)).not.toBeInTheDocument();

    await userEvent.click(toggle);

    // Expanding is shared state (MysteryMixClub-4vii.7): the mobile card's
    // own preview opens too, so pin the assertions to the table's copy.
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(table).getByText("great pick")).toBeInTheDocument();
    expect(within(table).getByText(/road trip/i)).toBeInTheDocument();
    expect(within(table).getByText(/my pick/i)).toBeInTheDocument();
  });

  it("toggles the preview when the row itself is clicked, not just the chevron", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith({ submitter_note: "my pick" })]);

    renderHistory();
    const table = await screen.findByRole("table");
    const cell = within(table).getByText("Song One");

    await userEvent.click(cell);

    expect(rowToggle("Song One")).toHaveAttribute("aria-expanded", "true");
    expect(within(table).getByText(/my pick/i)).toBeInTheDocument();
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
    const table = await screen.findByRole("table");

    // Grid cell shows "hidden" rather than a number for the open mix.
    expect(within(table).getByText("hidden")).toBeInTheDocument();
    expect(within(table).getByText("2")).toBeInTheDocument();

    await userEvent.click(rowToggle("Open Song"));
    expect(within(table).getByText(/votes reveal once this mix closes/i)).toBeInTheDocument();

    await userEvent.click(rowToggle("Closed Song"));
    expect(within(table).getByText(/voted by sam ×2/i)).toBeInTheDocument();
  });

  it("filters by title/artist search", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Blue Moon", artist: "Sinatra" }),
      entryWith({ submission_id: "s2", title: "Purple Rain", artist: "Prince" }),
    ]);

    renderHistory();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Blue Moon")).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/search/i), "prince");

    expect(within(table).queryByText("Blue Moon")).not.toBeInTheDocument();
    expect(within(table).getByText("Purple Rain")).toBeInTheDocument();
  });

  it("sorts by clicking the song column header", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Zebra", artist: "Z" }),
      entryWith({ submission_id: "s2", title: "Apple", artist: "A" }),
    ]);

    renderHistory();
    await screen.findByRole("table");

    await userEvent.click(screen.getByRole("button", { name: "song" }));

    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    const titles = rows.map((r) => r.textContent);
    expect(titles[0]).toContain("Apple");
    expect(titles[1]).toContain("Zebra");
  });

  it("navigates to the mix from the expanded preview's link", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith({ mix_id: "mix-42" })]);

    renderHistory();
    const table = await screen.findByRole("table");
    await userEvent.click(rowToggle("Song One"));
    // The mobile card's own preview renders an identical "open mix" button
    // (shared expanded state, MysteryMixClub-4vii.7) -- scope to the table's.
    await userEvent.click(within(table).getByRole("button", { name: /open mix/i }));

    expect(await screen.findByText("MIX DETAIL CONTENT")).toBeInTheDocument();
  });

  it("paginates once there are more than 25 submissions, and resets to page 1 on search", async () => {
    const entries = Array.from({ length: 30 }, (_, i) =>
      entryWith({
        submission_id: `s${i}`,
        title: `Song ${String(i).padStart(2, "0")}`,
        artist: "Artist",
      }),
    );
    mockGetMySubmissionHistory.mockResolvedValue(entries);

    renderHistory();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Song 00")).toBeInTheDocument();

    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
    expect(within(table).queryByText("Song 25")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /prev/i })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    expect(await within(table).findByText("Song 25")).toBeInTheDocument();
    expect(within(table).queryByText("Song 00")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();

    // Typing a search (even one that matches everything) should snap back to
    // page 1 -- otherwise a search from page 2 could render an empty grid if
    // the new result set has fewer pages than the one being viewed.
    await userEvent.type(screen.getByLabelText(/search/i), "Song");

    expect(await within(table).findByText("Song 00")).toBeInTheDocument();
    expect(screen.getByText(/page 1 of 2/i)).toBeInTheDocument();
  });

  it("has no pagination control when everything fits on one page", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith()]);

    renderHistory();
    await screen.findByRole("table");

    expect(screen.queryByRole("navigation", { name: /pagination/i })).not.toBeInTheDocument();
  });

  it("mirrors every table row as a mobile card with a sort-by select (MysteryMixClub-4vii.7)", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        title: "Song One",
        artist: "Artist One",
        club_name: "Friday Mixtape",
        mix_number: 3,
        created_at: "2026-03-05T00:00:00Z",
        vote_count: 4,
        notes: [
          {
            id: "note-1",
            author_id: "user-sam",
            body: "nice",
            author_display_name: "Sam",
            created_at: "2026-03-06T00:00:00Z",
          },
        ],
      }),
    ]);

    renderHistory();
    await screen.findByRole("table");

    const card = within(screen.getByRole("list")).getByRole("listitem");
    expect(within(card).getByText("Song One")).toBeInTheDocument();
    expect(within(card).getByText("Artist One")).toBeInTheDocument();
    expect(within(card).getByText(/friday/i)).toBeInTheDocument();
    expect(within(card).getByText(/mixtape/i)).toBeInTheDocument();
    expect(within(card).getByText(/4 votes/i)).toBeInTheDocument();
    expect(within(card).getByText(/1 note/i)).toBeInTheDocument();

    expect(screen.getByLabelText(/sort by/i)).toBeInTheDocument();
  });

  it("expands the mobile card's own detail panel when its toggle is tapped", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submitter_note: "my pick", theme: "road trip" }),
    ]);

    renderHistory();
    await screen.findByRole("table");

    const card = within(screen.getByRole("list")).getByRole("listitem");
    const toggle = within(card).getByRole("button", { name: /show details for song one/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(card).queryByText(/my pick/i)).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByText(/my pick/i)).toBeInTheDocument();
    expect(within(card).getByText(/road trip/i)).toBeInTheDocument();
  });

  it("sorts via the mobile select control, same as the desktop column header", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Zebra", artist: "Z" }),
      entryWith({ submission_id: "s2", title: "Apple", artist: "A" }),
    ]);

    renderHistory();
    await screen.findByRole("table");

    await userEvent.selectOptions(screen.getByLabelText(/sort by/i), "title");

    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    const titles = rows.map((r) => r.textContent);
    expect(titles[0]).toContain("Apple");
    expect(titles[1]).toContain("Zebra");
  });

  it("shows the server's error message when the load fails", async () => {
    mockGetMySubmissionHistory.mockRejectedValue(new ApiError(500, "server error"));

    renderHistory();

    // Mirrors ProfileRoute's pattern: an ApiError's own message passes
    // through verbatim; the generic fallback is only for a non-ApiError throw.
    expect(await screen.findByRole("alert")).toHaveTextContent("server error");
  });
});
