import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateClubScreen } from "./CreateClubScreen";

// Two DeadlineWindowFields ("submission window" / "voting window") share the
// same "days"/"hours" labels, so we look up their inputs by id instead of
// label text.
function renderScreen(overrides: Partial<Parameters<typeof CreateClubScreen>[0]> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const utils = render(
    <CreateClubScreen
      onSubmit={onSubmit}
      submitting={false}
      error={null}
      onCancel={onCancel}
      {...overrides}
    />,
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
