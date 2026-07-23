import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CreateClubRoute } from "./CreateClubRoute";
import { ApiError, createClub } from "../services/api";
import type { Club } from "../services/api";

// Mock the API module (no network). Keep ApiError real.
vi.mock("../services/api", async () => {
  const actual = await vi.importActual<typeof import("../services/api")>(
    "../services/api",
  );
  return {
    ...actual,
    createClub: vi.fn(),
  };
});

const mockCreateClub = vi.mocked(createClub);

function clubWith(overrides: Partial<Club> = {}): Club {
  return {
    id: "new-club-99",
    name: "Friday Mixtape",
    description: null,
    organizer_id: "22222222-2222-2222-2222-222222222222",
    total_mixes: 6,
    votes_per_player: 3,
    songs_per_submission: 1,
    current_mix: 0,
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
        <Route path="/clubs/new" element={<CreateClubRoute />} />
        <Route path="/home" element={<div>HOME CONTENT</div>} />
        <Route path="/clubs/:id" element={<div>CLUB DETAIL CONTENT</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CreateClubRoute", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("happy path: valid submit calls createClub and navigates to /clubs/{newId}", async () => {
    mockCreateClub.mockResolvedValue(clubWith({ id: "new-club-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("CLUB DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateClub).toHaveBeenCalledTimes(1);
    expect(mockCreateClub).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Friday Mixtape",
        total_mixes: 6,
        votes_per_player: 3,
        songs_per_submission: 1,
        default_vibe_mode: false,
      }),
    );
  });

  it("songs-per-submission field is sent through (MYS-116)", async () => {
    mockCreateClub.mockResolvedValue(clubWith({ id: "new-club-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Double Feature");
    fireEvent.change(screen.getByLabelText(/songs per submission/i), {
      target: { value: "3" },
    });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("CLUB DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateClub).toHaveBeenCalledWith(
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
    expect(mockCreateClub).not.toHaveBeenCalled();
  });

  it("just-vibing-by-default checkbox sends default_vibe_mode true (MYS-60)", async () => {
    mockCreateClub.mockResolvedValue(clubWith({ id: "new-club-99" }));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Casual Club");
    await user.click(screen.getByLabelText(/casual mode by default/i));
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByText("CLUB DETAIL CONTENT")).toBeInTheDocument();
    expect(mockCreateClub).toHaveBeenCalledWith(
      expect.objectContaining({ default_vibe_mode: true }),
    );
  });

  it("error: createClub rejecting shows the error and does not navigate", async () => {
    mockCreateClub.mockRejectedValue(new ApiError(422, "bad input"));
    const user = userEvent.setup();

    renderCreate();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("CLUB DETAIL CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("HOME CONTENT")).not.toBeInTheDocument();
  });

  it("cancel: navigates to /home", async () => {
    const user = userEvent.setup();

    renderCreate();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(await screen.findByText("HOME CONTENT")).toBeInTheDocument();
    expect(mockCreateClub).not.toHaveBeenCalled();
  });
});
