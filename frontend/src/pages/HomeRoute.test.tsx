import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { HomeRoute } from "./HomeRoute";
import { AuthedLayout } from "../components/AuthedLayout";
import { ApiError, getClubs } from "../services/api";
import type { Club } from "../services/api";
import { useAuth } from "../hooks/useAuth";

// Mock the API module (no network). Keep ApiError real so instanceof / status work.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>("../services/api");
  return {
    ...actual,
    getClubs: vi.fn(),
  };
});

// Mock useAuth so we drive displayName / logout directly.
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(),
}));

const mockGetClubs = vi.mocked(getClubs);
const mockUseAuth = vi.mocked(useAuth);
const logout = vi.fn();

function clubWith(overrides: Partial<Club> = {}): Club {
  return {
    id: "club-1",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "22222222-2222-2222-2222-222222222222",
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
    viewer_is_admin: false,
    ...overrides,
  };
}

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/home"]}>
      <Routes>
        {/* Mirror production: the route lives under AuthedLayout, which renders
            the shared TopNav once above the routed content. */}
        <Route element={<AuthedLayout />}>
          <Route path="/home" element={<HomeRoute />} />
        </Route>
        <Route path="/login" element={<div>LOGIN CONTENT</div>} />
        <Route path="/clubs/new" element={<div>NEW CLUB CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>CLUB DETAIL CONTENT</div>} />
        <Route path="/join/:token" element={<div>JOIN CONTENT</div>} />
        <Route path="/admin" element={<div>ADMIN CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("HomeRoute (My Clubs)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    logout.mockResolvedValue(undefined);
    mockGetClubs.mockResolvedValue([clubWith()]);
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      setAccessToken: vi.fn(),
      clear: vi.fn(),
      logout,
      logoutAll: vi.fn(),
      displayName: "ada",
      email: "ada@example.com",
      userId: "11111111-1111-1111-1111-111111111111",
      profileStatus: "ready",
      needsOnboarding: false,
      isPlatformAdmin: false,
      applyDisplayName: vi.fn(),
      preferredService: null,
      tosAccepted: true,
      applyTosAccepted: vi.fn(),
    });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("happy path: calls getClubs on mount and renders the club name", async () => {
    renderHome();

    expect(await screen.findByRole("heading", { name: "Friday Mixtape" })).toBeInTheDocument();
    expect(mockGetClubs).toHaveBeenCalledTimes(1);
  });

  it("groups completed clubs below active ones under a 'completed' heading with the crown marker", async () => {
    mockGetClubs.mockResolvedValue([
      clubWith({ id: "a1", name: "Active One", state: "active" }),
      clubWith({ id: "c1", name: "Finished One", state: "complete", current_mix: 6 }),
    ]);
    renderHome();

    const completedHeading = await screen.findByText("completed");
    const active = screen.getByRole("heading", { name: "Active One" });
    const done = screen.getByRole("heading", { name: "Finished One" });

    // Active club precedes the "completed" heading, which precedes the completed club.
    expect(
      active.compareDocumentPosition(completedHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      completedHeading.compareDocumentPosition(done) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Only the completed card wears the achievement marker. The marker is the
    // crown glyph (the only svg a club row renders) rather than the retired
    // gold left bar — see ClubCard for why completion carries no accent color.
    expect(done.closest("li")?.querySelector("svg")).not.toBeNull();
    expect(active.closest("li")?.querySelector("svg")).toBeNull();
  });

  it("admin: the chip follows the server's viewer_is_admin, not organizer_id", async () => {
    mockGetClubs.mockResolvedValue([
      // A co-organizer: NOT the organizer_id, but an admin all the same
      // (MYS-99). Deriving the chip from organizer_id would miss this club,
      // which is why the server computes the flag.
      clubWith({
        id: "co",
        name: "Co Organized",
        organizer_id: "22222222-2222-2222-2222-222222222222",
        viewer_is_admin: true,
      }),
      clubWith({
        id: "theirs",
        name: "Their Club",
        organizer_id: "22222222-2222-2222-2222-222222222222",
        viewer_is_admin: false,
      }),
    ]);
    renderHome();

    const co = (await screen.findByRole("heading", { name: "Co Organized" })).closest("li")!;
    const theirs = screen.getByRole("heading", { name: "Their Club" }).closest("li")!;

    expect(within(co).getByText("admin")).toBeInTheDocument();
    expect(within(theirs).queryByText("admin")).toBeNull();
  });

  it("admin: a null viewer_is_admin claims nothing", async () => {
    // null means "this endpoint didn't answer", which must not be read as true.
    // Being wrong in that direction would brand someone else's club as yours.
    mockGetClubs.mockResolvedValue([
      clubWith({ id: "x", name: "Some Club", viewer_is_admin: null }),
    ]);
    renderHome();

    const row = (await screen.findByRole("heading", { name: "Some Club" })).closest("li")!;
    expect(within(row).queryByText("admin")).toBeNull();
  });

  it("active clubs carry the status bar, completed ones do not", async () => {
    mockGetClubs.mockResolvedValue([
      clubWith({ id: "a1", name: "Active One", state: "active" }),
      clubWith({ id: "c1", name: "Finished One", state: "complete" }),
    ]);
    renderHome();

    const active = (await screen.findByRole("heading", { name: "Active One" })).closest("li")!;
    const done = screen.getByRole("heading", { name: "Finished One" }).closest("li")!;

    // Green, not amber: active is the default state and would otherwise paint
    // nearly every row in the accent. See ClubCard for the full argument.
    expect(active.querySelector(".bg-positive")).not.toBeNull();
    expect(active.querySelector(".bg-accent")).toBeNull();
    expect(done.querySelector(".bg-positive")).toBeNull();
  });

  it("state is never carried by colour alone", async () => {
    // The bar is aria-hidden decoration, so WCAG 1.4.1 requires the state to be
    // readable as text. That is the Badge, and it is why the bar may be a colour
    // at all.
    mockGetClubs.mockResolvedValue([
      clubWith({ id: "a1", name: "Active One", state: "active" }),
      clubWith({ id: "c1", name: "Finished One", state: "complete" }),
    ]);
    renderHome();

    const active = (await screen.findByRole("heading", { name: "Active One" })).closest("li")!;
    const done = screen.getByRole("heading", { name: "Finished One" }).closest("li")!;

    expect(within(active).getByText("active")).toBeInTheDocument();
    expect(within(done).getByText("complete")).toBeInTheDocument();
    expect(active.querySelector(".bg-positive")).toHaveAttribute("aria-hidden", "true");
  });

  it("empty list: renders the empty-state copy", async () => {
    mockGetClubs.mockResolvedValue([]);
    renderHome();

    expect(await screen.findByText("no clubs yet")).toBeInTheDocument();
  });

  it("error: getClubs rejecting surfaces a calm error via the error prop", async () => {
    mockGetClubs.mockRejectedValue(new ApiError(500, "boom"));
    renderHome();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("create: the create-a-club action navigates to /clubs/new", async () => {
    mockGetClubs.mockResolvedValue([]);
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByRole("button", { name: /create a club/i }));

    expect(await screen.findByText("NEW CLUB CONTENT")).toBeInTheDocument();
  });

  it("open: clicking a club navigates to /clubs/{id}", async () => {
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByRole("heading", { name: "Friday Mixtape" }));

    expect(await screen.findByText("CLUB DETAIL CONTENT")).toBeInTheDocument();
  });

  it("logout: invokes useAuth().logout and navigates to /login", async () => {
    const user = userEvent.setup();
    renderHome();

    await screen.findByRole("heading", { name: "Friday Mixtape" });
    await user.click(screen.getByRole("button", { name: /^logout$/i }));

    expect(logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("LOGIN CONTENT")).toBeInTheDocument();
  });

  it("pending invite: a stored pendingInvitePath redirects there and clears the key", async () => {
    localStorage.setItem("pendingInvitePath", "/join/abc");
    renderHome();

    expect(await screen.findByText("JOIN CONTENT")).toBeInTheDocument();
    expect(localStorage.getItem("pendingInvitePath")).toBeNull();
  });

  it("admin nav: hidden for a non-admin", async () => {
    renderHome();

    await screen.findByRole("heading", { name: "Friday Mixtape" });
    expect(screen.queryByRole("button", { name: /^admin$/i })).not.toBeInTheDocument();
  });

  it("admin nav: a platform admin gets an admin entry that routes to /admin", async () => {
    mockUseAuth.mockReturnValue({
      status: "authenticated",
      isAuthenticated: true,
      setAccessToken: vi.fn(),
      clear: vi.fn(),
      logout,
      logoutAll: vi.fn(),
      displayName: "ada",
      email: "ada@example.com",
      userId: "11111111-1111-1111-1111-111111111111",
      profileStatus: "ready",
      needsOnboarding: false,
      isPlatformAdmin: true,
      applyDisplayName: vi.fn(),
      preferredService: null,
      tosAccepted: true,
      applyTosAccepted: vi.fn(),
    });
    const user = userEvent.setup();
    renderHome();

    await user.click(await screen.findByRole("button", { name: /^admin$/i }));

    expect(await screen.findByText("ADMIN CONTENT")).toBeInTheDocument();
  });
});
