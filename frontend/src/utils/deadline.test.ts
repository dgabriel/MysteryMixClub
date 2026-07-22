import { describe, expect, it } from "vitest";
import { formatCountdown, formatDeadline, toDatetimeLocalValue } from "./deadline";
import type { Mix } from "../services/api";

// A full Mix with only the fields formatDeadline reads meaningfully; overrides
// set state and the two deadline strings per case.
function mixWith(overrides: Partial<Mix> = {}): Mix {
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

// Mid-day UTC so the browser-local calendar date can't roll into an adjacent
// month in any real timezone — the month label stays stable. July vs December
// lets a test prove which deadline field was chosen.
const JULY = "2026-07-05T12:00:00Z";
const DECEMBER = "2026-12-20T12:00:00Z";

describe("formatDeadline", () => {
  it("open_submission → uses the submission deadline", () => {
    const out = formatDeadline(
      mixWith({ state: "open_submission", submission_deadline: JULY, voting_deadline: DECEMBER }),
    );
    expect(out).toMatch(/^closes /);
    expect(out).toContain("jul"); // submission (July), not voting (December)
    expect(out).not.toContain("dec");
    // Copy is emitted lowercase (the uppercase is CSS-only).
    expect(out).toBe(out?.toLowerCase());
  });

  it("open_voting → uses the voting deadline", () => {
    const out = formatDeadline(
      mixWith({ state: "open_voting", submission_deadline: JULY, voting_deadline: DECEMBER }),
    );
    expect(out).toMatch(/^closes /);
    expect(out).toContain("dec"); // voting (December), not submission (July)
    expect(out).not.toContain("jul");
  });

  it("pending → null even when deadlines are set", () => {
    expect(
      formatDeadline(
        mixWith({ state: "pending", submission_deadline: JULY, voting_deadline: DECEMBER }),
      ),
    ).toBeNull();
  });

  it("closed → null even when deadlines are set", () => {
    expect(
      formatDeadline(
        mixWith({ state: "closed", submission_deadline: JULY, voting_deadline: DECEMBER }),
      ),
    ).toBeNull();
  });

  it("open_submission with a null submission deadline → null (legacy mix)", () => {
    expect(
      formatDeadline(mixWith({ state: "open_submission", submission_deadline: null })),
    ).toBeNull();
  });

  it("open_voting with a null voting deadline → null (legacy mix)", () => {
    expect(formatDeadline(mixWith({ state: "open_voting", voting_deadline: null }))).toBeNull();
  });

  it("invalid date string → null", () => {
    expect(
      formatDeadline(mixWith({ state: "open_submission", submission_deadline: "not-a-date" })),
    ).toBeNull();
  });
});

describe("formatCountdown", () => {
  // Fixed reference "now" — offsets below are computed from this instant so the
  // expected d/h/m breakdown is exact and not subject to wall-clock flakiness.
  // Deliberately earlier than both JULY and DECEMBER so those constants remain
  // usable as future deadlines in the phase-selection test below.
  const NOW = new Date("2026-07-01T12:00:00Z");

  function offsetFrom(now: Date, ms: number): string {
    return new Date(now.getTime() + ms).toISOString();
  }

  it('multi-day remaining → "Xd Yh remaining"', () => {
    const deadline = offsetFrom(NOW, (2 * 24 + 14) * 60 * 60 * 1000); // 2d 14h out
    const out = formatCountdown(
      mixWith({ state: "open_submission", submission_deadline: deadline }),
      NOW,
    );
    expect(out).toBe("2d 14h remaining");
  });

  it('under-a-day remaining → "Xh Ym remaining", not "0d Xh"', () => {
    const deadline = offsetFrom(NOW, (3 * 60 + 12) * 60 * 1000); // 3h 12m out
    const out = formatCountdown(
      mixWith({ state: "open_submission", submission_deadline: deadline }),
      NOW,
    );
    expect(out).toBe("3h 12m remaining");
    expect(out).not.toMatch(/^0d/);
  });

  it('deadline exactly now → "closing soon…"', () => {
    const out = formatCountdown(
      mixWith({ state: "open_submission", submission_deadline: NOW.toISOString() }),
      NOW,
    );
    expect(out).toBe("closing soon…");
  });

  it('deadline already passed → "closing soon…"', () => {
    const deadline = offsetFrom(NOW, -60_000); // 1 minute in the past
    const out = formatCountdown(
      mixWith({ state: "open_submission", submission_deadline: deadline }),
      NOW,
    );
    expect(out).toBe("closing soon…");
  });

  it("pending → null even when deadlines are set", () => {
    expect(
      formatCountdown(
        mixWith({ state: "pending", submission_deadline: JULY, voting_deadline: DECEMBER }),
        NOW,
      ),
    ).toBeNull();
  });

  it("closed → null even when deadlines are set", () => {
    expect(
      formatCountdown(
        mixWith({ state: "closed", submission_deadline: JULY, voting_deadline: DECEMBER }),
        NOW,
      ),
    ).toBeNull();
  });

  it("open_submission with a null submission deadline → null (legacy mix)", () => {
    expect(
      formatCountdown(mixWith({ state: "open_submission", submission_deadline: null }), NOW),
    ).toBeNull();
  });

  it("open_voting with a null voting deadline → null (legacy mix)", () => {
    expect(
      formatCountdown(mixWith({ state: "open_voting", voting_deadline: null }), NOW),
    ).toBeNull();
  });

  it("invalid date string → null", () => {
    expect(
      formatCountdown(
        mixWith({ state: "open_submission", submission_deadline: "not-a-date" }),
        NOW,
      ),
    ).toBeNull();
  });

  it("open_submission → uses the submission deadline, not voting", () => {
    // JULY is ~ a day+ after NOW; DECEMBER is far in the future — proves the
    // submission field (JULY) drives the countdown, not voting (DECEMBER).
    const out = formatCountdown(
      mixWith({ state: "open_submission", submission_deadline: JULY, voting_deadline: DECEMBER }),
      NOW,
    );
    const outIfVoting = formatCountdown(
      mixWith({ state: "open_voting", submission_deadline: JULY, voting_deadline: DECEMBER }),
      NOW,
    );
    expect(out).not.toBe(outIfVoting);
  });

  it("open_voting → uses the voting deadline, not submission", () => {
    const deadline = offsetFrom(NOW, 5 * 60 * 60 * 1000); // 5h out
    const out = formatCountdown(
      mixWith({
        state: "open_voting",
        submission_deadline: offsetFrom(NOW, 60 * 60 * 1000), // 1h out — should be ignored
        voting_deadline: deadline,
      }),
      NOW,
    );
    expect(out).toBe("5h 0m remaining");
  });
});

describe("toDatetimeLocalValue", () => {
  it("pads single-digit month/day/hour/minute to two digits", () => {
    const out = toDatetimeLocalValue(new Date(2026, 0, 5, 9, 5)); // Jan 5, 09:05, local
    expect(out).toBe("2026-01-05T09:05");
  });

  it("round-trips through new Date() back to the same local wall-clock time", () => {
    const original = new Date(2026, 6, 22, 14, 30);
    const formatted = toDatetimeLocalValue(original);
    const reparsed = new Date(formatted);
    expect(reparsed.getTime()).toBe(original.getTime());
  });
});
