import { describe, expect, it } from "vitest";
import {
  daysAndHoursToTotal,
  hoursToDaysAndHours,
  MAX_WINDOW_HOURS,
  MIN_WINDOW_HOURS,
  validateWindowHours,
} from "./deadlineWindow";

describe("hoursToDaysAndHours", () => {
  it.each([
    [0, { days: 0, hours: 0 }],
    [4, { days: 0, hours: 4 }],
    [72, { days: 3, hours: 0 }],
    [102, { days: 4, hours: 6 }],
    [168, { days: 7, hours: 0 }],
  ])("%dh -> %o", (totalHours, expected) => {
    expect(hoursToDaysAndHours(totalHours)).toEqual(expected);
  });
});

describe("daysAndHoursToTotal", () => {
  it.each([
    [0, 0, 0],
    [0, 4, 4],
    [3, 0, 72],
    [4, 6, 102],
    [7, 0, 168],
  ])("%d days, %d hours -> %dh", (days, hours, expected) => {
    expect(daysAndHoursToTotal(days, hours)).toBe(expected);
  });

  it("round-trips with hoursToDaysAndHours for every integer total between 4 and 168", () => {
    for (let totalHours = MIN_WINDOW_HOURS; totalHours <= MAX_WINDOW_HOURS; totalHours++) {
      const { days, hours } = hoursToDaysAndHours(totalHours);
      expect(daysAndHoursToTotal(days, hours)).toBe(totalHours);
    }
  });
});

describe("validateWindowHours", () => {
  it("below the minimum returns the too-short message", () => {
    expect(validateWindowHours(2)).toBe(`windows need at least ${MIN_WINDOW_HOURS} hours.`);
  });

  it("exactly the minimum is valid (boundary inclusive, matches API ge=4)", () => {
    expect(validateWindowHours(MIN_WINDOW_HOURS)).toBeNull();
  });

  it("exactly the maximum is valid (boundary inclusive, matches API le=168)", () => {
    expect(validateWindowHours(MAX_WINDOW_HOURS)).toBeNull();
  });

  it("above the maximum returns the too-long message", () => {
    expect(validateWindowHours(200)).toBe(
      `windows can't be longer than ${MAX_WINDOW_HOURS} hours (1 week).`,
    );
  });

  it.each([3.5, 100.1])(
    "non-integer total (%s) returns the whole-days-and-hours message",
    (totalHours) => {
      expect(validateWindowHours(totalHours)).toBe("enter whole days and hours.");
    },
  );

  it.each([NaN, Infinity, -Infinity])(
    "non-finite total (%s) returns the invalid-duration message",
    (totalHours) => {
      expect(validateWindowHours(totalHours)).toBe("enter a valid duration.");
    },
  );
});
