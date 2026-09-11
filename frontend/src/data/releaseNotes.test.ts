import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  RELEASE_NOTES,
  formatReleaseDate,
  hasUnseenRelease,
  latestReleaseDate,
  markLatestReleaseSeen,
} from "./releaseNotes";

describe("releaseNotes", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("latestReleaseDate returns the first (newest) entry's date", () => {
    expect(latestReleaseDate()).toBe(RELEASE_NOTES[0].date);
  });

  it("hasUnseenRelease is true when nothing has been marked seen yet", () => {
    expect(hasUnseenRelease()).toBe(true);
  });

  it("hasUnseenRelease is false once markLatestReleaseSeen has run", () => {
    markLatestReleaseSeen();
    expect(hasUnseenRelease()).toBe(false);
  });

  it("hasUnseenRelease is true again if the stored date is older than the latest entry", () => {
    localStorage.setItem("lastSeenReleaseDate", "2000-01-01");
    expect(hasUnseenRelease()).toBe(true);
  });

  it("formatReleaseDate renders a lowercase month/day/year", () => {
    expect(formatReleaseDate("2026-09-09")).toMatch(/^[a-z]{3} 9, 2026$/);
  });

  it("formatReleaseDate falls back to the raw string for an unparseable date", () => {
    expect(formatReleaseDate("not-a-date")).toBe("not-a-date");
  });
});
