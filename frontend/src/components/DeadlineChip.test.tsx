import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { DeadlineChip } from "./DeadlineChip";
import type { Round } from "../services/api";

// A full Round with only the fields DeadlineChip / its helpers read
// meaningfully; overrides set state and the two deadline strings per case.
// Mirrors the roundWith fixture in utils/deadline.test.ts.
function roundWith(overrides: Partial<Round> = {}): Round {
  return {
    id: "r1",
    club_id: "lg1",
    mix_number: 1,
    theme: null,
    state: "open_submission",
    description: null,
    submission_deadline: null,
    voting_deadline: null,
    votes_per_player: 3,
    created_at: "2026-01-01T00:00:00Z",
    closed_at: null,
    submission_count: 0,
    member_count: 0,
    viewer_submitted: false,
    viewer_voted: false,
    voted_count: 0,
    voting_eligible_count: 0,
    ...overrides,
  };
}

describe("DeadlineChip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-01T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders label-only when showCountdown is omitted (no regression)", () => {
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-05T12:00:00Z",
    });
    const { container } = render(<DeadlineChip round={round} />);

    expect(container.textContent).toMatch(/^closes /);
    expect(container.textContent).not.toContain("·");
    expect(container.textContent).not.toContain("remaining");
  });

  it("renders label-only when showCountdown is explicitly false (no regression)", () => {
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-05T12:00:00Z",
    });
    const { container } = render(<DeadlineChip round={round} showCountdown={false} />);

    expect(container.textContent).not.toContain("·");
    expect(container.textContent).not.toContain("remaining");
  });

  it("renders \"{label} · {countdown}\" when showCountdown is true", () => {
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-05T12:00:00Z", // 4 days out from system time
    });
    const { container } = render(<DeadlineChip round={round} showCountdown /> );

    expect(container.textContent).toMatch(/^closes .* · 4d 0h remaining$/);
  });

  it("updates the displayed countdown after time advances past a minute boundary", () => {
    // Deadline is 59 minutes and 30 seconds out — under a day, so it renders
    // "0h 59m remaining" at mount. Advancing the fake clock by a full minute
    // should tick the interval and cross the minute boundary to "0h 58m".
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-01T12:59:30Z",
    });
    render(<DeadlineChip round={round} showCountdown />);

    expect(screen.getByText(/0h 59m remaining/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(60_000);
    });

    expect(screen.getByText(/0h 58m remaining/)).toBeInTheDocument();
    expect(screen.queryByText(/0h 59m remaining/)).not.toBeInTheDocument();
  });

  it("clears the interval on unmount", () => {
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-05T12:00:00Z",
    });
    const { unmount } = render(<DeadlineChip round={round} showCountdown />);

    unmount();

    expect(clearIntervalSpy).toHaveBeenCalled();
  });

  it("does not set up an interval at all when showCountdown is false", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const round = roundWith({
      state: "open_submission",
      submission_deadline: "2026-07-05T12:00:00Z",
    });
    render(<DeadlineChip round={round} />);

    expect(setIntervalSpy).not.toHaveBeenCalled();
  });

  it("renders nothing when the round has no active-phase deadline, without showCountdown", () => {
    const round = roundWith({ state: "pending" });
    const { container } = render(<DeadlineChip round={round} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the round has no active-phase deadline, with showCountdown", () => {
    const round = roundWith({ state: "pending" });
    const { container } = render(<DeadlineChip round={round} showCountdown />);

    expect(container).toBeEmptyDOMElement();
  });
});
