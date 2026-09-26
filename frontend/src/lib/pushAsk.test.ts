import { beforeEach, describe, expect, it } from "vitest";
import { MAX_PUSH_ASKS, PUSH_ASK_INTERVAL_MS, recordPushAsk, shouldAskForPush } from "./pushAsk";

describe("push ask cadence (MysteryMixClub-gxh3): up to 3 times, a week apart", () => {
  beforeEach(() => localStorage.clear());

  it("asks the first time", () => {
    expect(shouldAskForPush("u1", 1000)).toBe(true);
  });

  it("not again within a week, then again after one", () => {
    recordPushAsk("u1", 0);
    expect(shouldAskForPush("u1", PUSH_ASK_INTERVAL_MS - 1)).toBe(false);
    expect(shouldAskForPush("u1", PUSH_ASK_INTERVAL_MS)).toBe(true);
  });

  it("never after the third ask", () => {
    for (let i = 0; i < MAX_PUSH_ASKS; i++) recordPushAsk("u1", i * PUSH_ASK_INTERVAL_MS);
    expect(shouldAskForPush("u1", 100 * PUSH_ASK_INTERVAL_MS)).toBe(false);
  });

  it("is kept per account", () => {
    for (let i = 0; i < MAX_PUSH_ASKS; i++) recordPushAsk("u1", 0);
    expect(shouldAskForPush("u2", 0)).toBe(true);
  });
});
