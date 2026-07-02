import { describe, expect, it } from "vitest";
import { formatDeadline } from "./deadline";
import type { Round } from "../services/api";

// A full Round with only the fields formatDeadline reads meaningfully; overrides
// set state and the two deadline strings per case.
function roundWith(overrides: Partial<Round> = {}): Round {
  return {
    id: "r1",
    league_id: "lg1",
    round_number: 1,
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
      roundWith({ state: "open_submission", submission_deadline: JULY, voting_deadline: DECEMBER }),
    );
    expect(out).toMatch(/^closes /);
    expect(out).toContain("jul"); // submission (July), not voting (December)
    expect(out).not.toContain("dec");
    // Copy is emitted lowercase (the uppercase is CSS-only).
    expect(out).toBe(out?.toLowerCase());
  });

  it("open_voting → uses the voting deadline", () => {
    const out = formatDeadline(
      roundWith({ state: "open_voting", submission_deadline: JULY, voting_deadline: DECEMBER }),
    );
    expect(out).toMatch(/^closes /);
    expect(out).toContain("dec"); // voting (December), not submission (July)
    expect(out).not.toContain("jul");
  });

  it("pending → null even when deadlines are set", () => {
    expect(
      formatDeadline(
        roundWith({ state: "pending", submission_deadline: JULY, voting_deadline: DECEMBER }),
      ),
    ).toBeNull();
  });

  it("closed → null even when deadlines are set", () => {
    expect(
      formatDeadline(
        roundWith({ state: "closed", submission_deadline: JULY, voting_deadline: DECEMBER }),
      ),
    ).toBeNull();
  });

  it("open_submission with a null submission deadline → null (legacy round)", () => {
    expect(
      formatDeadline(roundWith({ state: "open_submission", submission_deadline: null })),
    ).toBeNull();
  });

  it("open_voting with a null voting deadline → null (legacy round)", () => {
    expect(formatDeadline(roundWith({ state: "open_voting", voting_deadline: null }))).toBeNull();
  });

  it("invalid date string → null", () => {
    expect(
      formatDeadline(roundWith({ state: "open_submission", submission_deadline: "not-a-date" })),
    ).toBeNull();
  });
});
