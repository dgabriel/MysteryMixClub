import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  consumeJustJoinedClub,
  dismissGuide,
  isGuideDismissed,
  markJustJoinedClub,
} from "./onboardingGuides";

describe("onboardingGuides", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe("per-account dismissal", () => {
    it("is not dismissed until dismissGuide is called", () => {
      expect(isGuideDismissed("emptyClubs", "user-1")).toBe(false);
    });

    it("is dismissed for that account once dismissGuide runs", () => {
      dismissGuide("emptyClubs", "user-1");
      expect(isGuideDismissed("emptyClubs", "user-1")).toBe(true);
    });

    it("scopes dismissal per account -- another account's guide is unaffected", () => {
      dismissGuide("emptyClubs", "user-1");
      expect(isGuideDismissed("emptyClubs", "user-2")).toBe(false);
    });

    it("scopes dismissal per guide -- dismissing one guide doesn't dismiss the other", () => {
      dismissGuide("emptyClubs", "user-1");
      expect(isGuideDismissed("invite", "user-1")).toBe(false);
    });
  });

  describe("the one-shot just-joined flag", () => {
    it("reads false when nothing was marked", () => {
      expect(consumeJustJoinedClub("club-1")).toBe(false);
    });

    it("reads true exactly once for the club it was marked for", () => {
      markJustJoinedClub("club-1");
      expect(consumeJustJoinedClub("club-1")).toBe(true);
      expect(consumeJustJoinedClub("club-1")).toBe(false);
    });

    it("reads false for a different club than the one marked, and still consumes the flag", () => {
      markJustJoinedClub("club-1");
      expect(consumeJustJoinedClub("club-2")).toBe(false);
      // Consumed regardless of the mismatch, so it can't later misfire on club-1 either.
      expect(consumeJustJoinedClub("club-1")).toBe(false);
    });
  });
});
