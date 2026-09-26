import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  RECONNECTED_MS,
  getConnectivityPhase,
  onBackOnline,
  reportNetworkFailure,
  reportNetworkSuccess,
  resetConnectivityForTests,
  setConnectivityProbe,
  waitUntilOnline,
} from "./connectivity";

describe("connectivity store (MysteryMixClub-ga4y)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetConnectivityForTests();
  });

  afterEach(() => {
    resetConnectivityForTests();
    vi.useRealTimers();
  });

  it("a failed request means offline; a response means back online, briefly 'reconnected'", () => {
    const backOnline = vi.fn();
    onBackOnline(backOnline);

    reportNetworkFailure();
    expect(getConnectivityPhase()).toBe("offline");

    reportNetworkSuccess();
    expect(getConnectivityPhase()).toBe("reconnected");
    expect(backOnline).not.toHaveBeenCalled();

    vi.advanceTimersByTime(RECONNECTED_MS);
    expect(getConnectivityPhase()).toBe("online");
    expect(backOnline).toHaveBeenCalledTimes(1);
  });

  it("the browser's offline and online events drive it too", () => {
    window.dispatchEvent(new Event("offline"));
    expect(getConnectivityPhase()).toBe("offline");

    window.dispatchEvent(new Event("online"));
    expect(getConnectivityPhase()).toBe("reconnected");
  });

  it("while offline after a failed request, the health probe retries until the API answers", async () => {
    const probe = vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    setConnectivityProbe(probe);

    reportNetworkFailure();
    await vi.advanceTimersByTimeAsync(5000);
    expect(getConnectivityPhase()).toBe("offline");

    await vi.advanceTimersByTimeAsync(5000);
    expect(probe).toHaveBeenCalledTimes(2);
    expect(getConnectivityPhase()).toBe("reconnected");
  });

  it("waitUntilOnline resolves only once the connection is back", async () => {
    reportNetworkFailure();
    let resolved = false;
    void waitUntilOnline().then(() => {
      resolved = true;
    });

    await Promise.resolve();
    expect(resolved).toBe(false);

    reportNetworkSuccess();
    await Promise.resolve();
    expect(resolved).toBe(true);
  });

  it("going offline again during 'back online' cancels the reload signal", () => {
    const backOnline = vi.fn();
    onBackOnline(backOnline);
    reportNetworkFailure();
    reportNetworkSuccess();

    reportNetworkFailure();
    vi.advanceTimersByTime(RECONNECTED_MS * 2);

    expect(getConnectivityPhase()).toBe("offline");
    expect(backOnline).not.toHaveBeenCalled();
  });
});
