import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Regression cover for MysteryMixClub-ljl5.
 *
 * The bug these guard against was not a wrong result, it was *no* result: a
 * blocked MusicKit script fires neither `musickitloaded` nor the script's
 * `error` event, so the loader's promise stayed pending forever and the caller
 * sat on "building…" with no error. Every assertion here is that a promise
 * settles at all.
 *
 * jsdom does not fetch the injected script, so it models the blocked case
 * exactly: the element is appended and nothing ever fires.
 */

// Fresh module state per test — the loader caches its promise across calls.
async function loadModule() {
  vi.resetModules();
  return import("./musickit");
}

/** The script the *current* module instance injected. Each test resets modules
 *  but shares one document, so without this a dispatched event can land on a
 *  leftover element belonging to an already-settled loader. */
function injectedScript(): HTMLScriptElement {
  const scripts = document.querySelectorAll<HTMLScriptElement>('script[src*="musickit"]');
  expect(scripts.length).toBe(1);
  return scripts[0];
}

function clearInjectedScripts() {
  document.querySelectorAll('script[src*="musickit"]').forEach((s) => s.remove());
}

beforeEach(() => {
  vi.useFakeTimers();
  clearInjectedScripts();
  delete window.MusicKit;
});

afterEach(() => {
  vi.useRealTimers();
  clearInjectedScripts();
  delete window.MusicKit;
});

describe("preloadAppleMusic", () => {
  it("rejects rather than hanging when apple's sdk never loads", async () => {
    const { preloadAppleMusic, AppleMusicError } = await loadModule();

    const pending = preloadAppleMusic("dev-token");
    const assertion = expect(pending).rejects.toThrowError(AppleMusicError);
    await vi.advanceTimersByTimeAsync(20_000);

    await assertion;
    await expect(pending).rejects.toMatchObject({ kind: "sdk_blocked" });
  });

  it("reports a refused script as blocked without waiting out the timeout", async () => {
    const { preloadAppleMusic } = await loadModule();

    const pending = preloadAppleMusic("dev-token");
    // The one failure the original code did handle: an outright network error.
    injectedScript().dispatchEvent(new Event("error"));

    await expect(pending).rejects.toMatchObject({ kind: "sdk_blocked" });
  });

  it("retries the load after a failure instead of replaying the rejection", async () => {
    const { preloadAppleMusic } = await loadModule();

    const first = preloadAppleMusic("dev-token");
    injectedScript().dispatchEvent(new Event("error"));
    await expect(first).rejects.toMatchObject({ kind: "sdk_blocked" });

    // A cached rejected promise would leave Apple permanently broken for the
    // rest of the session, so a second attempt must inject a second script.
    clearInjectedScripts();
    void preloadAppleMusic("dev-token").catch(() => {});
    expect(injectedScript()).toBeInstanceOf(HTMLScriptElement);
  });

  it("configures once and reuses the instance for the same token", async () => {
    const { preloadAppleMusic } = await loadModule();
    const authorize = vi.fn();
    const configure = vi.fn().mockResolvedValue(undefined);
    window.MusicKit = { configure, getInstance: () => ({ authorize }) };

    await preloadAppleMusic("dev-token");
    await preloadAppleMusic("dev-token");

    expect(configure).toHaveBeenCalledTimes(1);
  });
});

describe("authorizeAppleMusic", () => {
  it("reaches authorize() synchronously once warmed", async () => {
    const { preloadAppleMusic, authorizeAppleMusic } = await loadModule();
    const authorize = vi.fn().mockResolvedValue("mut-123");
    window.MusicKit = { configure: vi.fn().mockResolvedValue(undefined), getInstance: () => ({
      authorize,
    }) };

    await preloadAppleMusic("dev-token");

    // The load-bearing assertion of the whole fix: no await may sit in front of
    // authorize() on the warm path, or mobile Safari drops the user activation
    // and never opens the sign-in window. Calling without awaiting proves it
    // ran in this tick — the same tick as the tap, in the browser.
    void authorizeAppleMusic("dev-token");
    expect(authorize).toHaveBeenCalled();
  });

  it("rejects rather than hanging when sign-in never completes", async () => {
    const { preloadAppleMusic, authorizeAppleMusic } = await loadModule();
    window.MusicKit = {
      configure: vi.fn().mockResolvedValue(undefined),
      // A window that is blocked or dismissed leaves this pending forever.
      getInstance: () => ({ authorize: () => new Promise<string>(() => {}) }),
    };

    await preloadAppleMusic("dev-token");
    const pending = authorizeAppleMusic("dev-token");
    const assertion = expect(pending).rejects.toMatchObject({ kind: "authorize_failed" });
    await vi.advanceTimersByTimeAsync(200_000);

    await assertion;
  });

  it("classifies an outright authorize failure as a sign-in problem", async () => {
    const { preloadAppleMusic, authorizeAppleMusic } = await loadModule();
    window.MusicKit = {
      configure: vi.fn().mockResolvedValue(undefined),
      getInstance: () => ({ authorize: () => Promise.reject(new Error("user closed it")) }),
    };

    await preloadAppleMusic("dev-token");

    await expect(authorizeAppleMusic("dev-token")).rejects.toMatchObject({
      kind: "authorize_failed",
    });
  });
});
