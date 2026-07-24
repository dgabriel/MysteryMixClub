import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CreateClubScreen } from "./CreateClubScreen";

// Two DeadlineWindowFields ("submission window" / "voting window") share the
// same "days"/"hours" labels, so we look up their inputs by id instead of
// label text.
function renderScreen(overrides: Partial<Parameters<typeof CreateClubScreen>[0]> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <MemoryRouter>
      <CreateClubScreen
        onSubmit={onSubmit}
        submitting={false}
        error={null}
        onCancel={onCancel}
        {...overrides}
      />
    </MemoryRouter>,
  );
  const getInput = (id: string) => utils.container.querySelector(`#${id}`) as HTMLInputElement;
  return { onSubmit, onCancel, ...utils, getInput };
}

describe("CreateClubScreen — deadline windows (MYS-160)", () => {
  it("defaults render as 3 days / 0 hours for both submission and voting windows", () => {
    const { getInput } = renderScreen();

    expect(getInput("submission-window-days").value).toBe("3");
    expect(getInput("submission-window-hours").value).toBe("0");
    expect(getInput("voting-window-days").value).toBe("3");
    expect(getInput("voting-window-hours").value).toBe("0");
  });

  it("happy path: submitting with defaults includes 72h windows in onSubmit", async () => {
    const { onSubmit } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        submission_window_hours: 72,
        voting_window_hours: 72,
      }),
    );
  });

  it("edge case: an out-of-range submission window (0 days 2 hours = 2h) blocks submit with a calm guard message", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("submission-window-days"), { target: { value: "0" } });
    fireEvent.change(getInput("submission-window-hours"), { target: { value: "2" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /submission windows need at least 4 hours\./i,
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("edge case: an out-of-range voting window blocks submit with a voting-prefixed guard message", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("voting-window-days"), { target: { value: "0" } });
    fireEvent.change(getInput("voting-window-hours"), { target: { value: "1" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /voting windows need at least 4 hours\./i,
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("valid non-default combination (4 days 6 hours = 102h) computes and submits the correct total", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("submission-window-days"), { target: { value: "4" } });
    fireEvent.change(getInput("submission-window-hours"), { target: { value: "6" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        submission_window_hours: 102,
        voting_window_hours: 72,
      }),
    );
  });
});

describe("CreateClubScreen — per-field validation consistency (MYS-121, MYS-239)", () => {
  // Regression coverage for MYS-239: number inputs carry native min/max
  // attributes, so without `noValidate` on the form these fields could be
  // intercepted by the browser's own validation UI instead of ever reaching
  // the app's calm-copy guard message. These boundary values (0, the lowest
  // value a browser would flag) are exactly the case that previously slipped
  // past this suite.
  it("form opts out of native HTML5 validation", () => {
    const { container } = renderScreen();
    const form = container.querySelector("form");
    expect(form).toHaveAttribute("novalidate");
  });

  it("total_mixes = 0 blocks submit with the app's own guard message and flags the field", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("club-total-mixes"), { target: { value: "0" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /a club needs at least one mystery mix\./i,
    );
    expect(getInput("club-total-mixes")).toHaveAttribute("aria-invalid", "true");
    expect(getInput("club-total-mixes")).toHaveAttribute(
      "aria-describedby",
      "club-total-mixes-error",
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("votes_per_player = 0 blocks submit with the app's own guard message and flags the field", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("club-votes-per-player"), { target: { value: "0" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /votes per player must be at least 1\./i,
    );
    expect(getInput("club-votes-per-player")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("songs_per_submission = 0 blocks submit with the app's own guard message and flags the field", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    fireEvent.change(getInput("club-songs-per-submission"), { target: { value: "0" } });
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /songs per submission must be between 1 and 5\./i,
    );
    expect(getInput("club-songs-per-submission")).toHaveAttribute("aria-invalid", "true");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("a valid submission never sets aria-invalid on any field", async () => {
    const { onSubmit, getInput } = renderScreen();
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "Friday Mixtape");
    await user.click(screen.getByRole("button", { name: /^create$/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    for (const id of [
      "club-name",
      "club-total-mixes",
      "club-votes-per-player",
      "club-songs-per-submission",
    ]) {
      expect(getInput(id)).not.toHaveAttribute("aria-invalid");
    }
  });
});
