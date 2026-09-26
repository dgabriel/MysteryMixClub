import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { usePushRegistration } from "./usePushRegistration";

// A controllable stand-in for the registration store in ios/push.
let state = "idle";
const subscribers = new Set<() => void>();
vi.mock("../ios/push", () => ({
  getPushRegistrationState: () => state,
  subscribePushRegistration: (notify: () => void) => {
    subscribers.add(notify);
    return () => {
      subscribers.delete(notify);
    };
  },
}));

function setState(next: string) {
  state = next;
  subscribers.forEach((notify) => notify());
}

describe("usePushRegistration (MysteryMixClub-4vii.32)", () => {
  it("reflects the current registration state and re-renders when it changes", () => {
    state = "idle";
    const { result } = renderHook(() => usePushRegistration());
    expect(result.current).toBe("idle");

    act(() => setState("registering"));
    expect(result.current).toBe("registering");

    act(() => setState("registered"));
    expect(result.current).toBe("registered");
  });

  it("stops listening when unmounted", () => {
    state = "idle";
    const { unmount } = renderHook(() => usePushRegistration());
    expect(subscribers.size).toBe(1);

    unmount();

    expect(subscribers.size).toBe(0);
  });
});
