import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CreateLeagueRoute } from "./CreateLeagueRoute";
import { ApiError, createLeague } from "../services/api";
import type { League } from "../services/api";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    createLeague: vi.fn(),
  };
});

const mockCreateLeague = vi.mocked(createLeague);

function leagueWith(overrides: Partial<League> = {}): League {
  return {
    id: "new-league-99",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "22222222-2222-2222-2222-222222222222",
    total_rounds: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_round: 0,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    default_vibe_mode: false,
    submission_window_hours: 72,
    voting_window_hours: 72,
    completed_at: null,
    ...overrides,
  };
}

function renderCreate() {
  return render(
    <MemoryRouter initialEntries={["/clubs/new"]}>
      <Routes>
        <Route path="/clubs/new" element={<CreateLeagueRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CreateLeagueRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("happy path: valid submit calls createLeague and navigates to /clubs/{newId}", async () => {
    mockCreateLeague.mockResolvedValue(leagueWith({ id: "new-league-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateLeague).toHaveBeenCalledTimes(1);
    expect(mockCreateLeague).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Friday Mixtape",
        total_rounds: 6,
        votes_per_player: 3,
        songs_per_submission: 1,
        default_vibe_mode: false,
      }),
    );
  });

  it("songs-per-submission field is sent through (MYS-116)", async () => {
    mockCreateLeague.mockResolvedValue(leagueWith({ id: "new-league-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Double Feature");
    fireEvent.change(screen.getByLabelText(/songs per submission/i), {
      target: { value: "3" },
    });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateLeague).toHaveBeenCalledWith(
      expect.objectContaining({ songs_per_submission: 3 }),
    );
  });

  it("rejects a songs-per-submission above 5 without calling the API", async () => {
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Too Many");
    // Force an out-of-range value: a real browser lets you type past `max`
    // (it just marks the field :invalid); jsdom/userEvent enforces max on type.
    fireEvent.change(screen.getByLabelText(/songs per submission/i), {
      target: { value: "6" },
    });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/between 1 and 5/i);
    expect(mockCreateLeague).not.toHaveBeenCalled();
  });

  it("just-vibing-by-default checkbox sends default_vibe_mode true (MYS-60)", async () => {
    mockCreateLeague.mockResolvedValue(leagueWith({ id: "new-league-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Vibes Only");
    await user.click(screen.getByLabelText(/just vibing by default/i));
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("LEAGUE DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateLeague).toHaveBeenCalledWith(
      expect.objectContaining({ default_vibe_mode: true }),
    );
  });

  it("error: createLeague rejecting shows the error and does not navigate", async () => {
    mockCreateLeague.mockRejectedValue(new ApiError(422, "bad input"));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("LEAGUE DETAIL CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
  });

  it("cancel: navigates to /home", async () => {
    const user = userEvent.setup();

    renderCreate();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
    expect(mockCreateLeague).not.toHaveBeenCalled();
  });
});
