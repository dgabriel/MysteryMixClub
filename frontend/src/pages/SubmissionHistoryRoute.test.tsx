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

  it("renders each submission with its club and mix context", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ title: "Song One", artist: "Artist One", club_name: "Friday Mixtape" }),
    ]);

    renderHistory();

    expect(await screen.findByText("Song One")).toBeInTheDocument();
    expect(screen.getByText("Artist One")).toBeInTheDocument();
    // ClubName splits a multi-word name across text nodes (its second word is
    // its own <span>), so "Friday Mixtape" doesn't match as one string --
    // check each word, same as the style guide documents for this component.
    expect(screen.getByText(/friday/i)).toBeInTheDocument();
    expect(screen.getByText(/mixtape/i)).toBeInTheDocument();
    expect(screen.getByText(/mix 1/i)).toBeInTheDocument();
  });

  it("hides vote data for a still-open mix and shows it once closed", async () => {
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
    expect(screen.getByText(/votes reveal once this mix closes/i)).toBeInTheDocument();
    expect(screen.getByText("2 votes")).toBeInTheDocument();
    expect(screen.getByText(/voted by sam ×2/i)).toBeInTheDocument();
  });

  it("keeps another player's notes collapsed behind a disclosure", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({
        notes: [{ body: "great pick", author_display_name: "Sam", created_at: "2026-01-02T00:00:00Z" }],
      }),
    ]);

    renderHistory();

    const toggle = await screen.findByRole("button", { name: /show 1 note/i });
    expect(screen.queryByText("great pick")).not.toBeInTheDocument();

    await userEvent.click(toggle);

    expect(screen.getByText("great pick")).toBeInTheDocument();
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

  it("sorts by title when the title control is selected", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([
      entryWith({ submission_id: "s1", title: "Zebra", artist: "Z" }),
      entryWith({ submission_id: "s2", title: "Apple", artist: "A" }),
    ]);

    renderHistory();
    await screen.findByText("Zebra");

    await userEvent.click(screen.getByRole("button", { name: "title" }));

    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(["Apple", "Zebra"]);
  });

  it("navigates to the mix when the row is clicked", async () => {
    mockGetMySubmissionHistory.mockResolvedValue([entryWith({ mix_id: "mix-42" })]);

    renderHistory();
    const title = await screen.findByText("Song One");
    // Clicking anywhere inside the row's button triggers navigation.
    await userEvent.click(title);

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
