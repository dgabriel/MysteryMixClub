import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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
    current_round: 0,
    state: "active",
    created_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function renderCreate() {
  return render(
    <MemoryRouter initialEntries={["/leagues/new"]}>
      <Routes>
        <Route path="/leagues/new" element={<CreateLeagueRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/leagues/:id" element={<div>LEAGUE DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CreateLeagueRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("happy path: valid submit calls createLeague and navigates to /leagues/{newId}", async () => {
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
      }),
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
