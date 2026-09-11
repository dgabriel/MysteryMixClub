import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";
import { markLatestReleaseSeen } from "../data/releaseNotes";

// Default test state is "a returning user who's already seen the current
// release" — AuthedLayout's release-notes auto-popup otherwise fires
// unpredictably in any test that renders it (depending on whatever earlier
// test in the same file last touched localStorage), injecting an unexpected
// modal (and its own <h3> date heading) into pages that never asked for it.
// A test that specifically wants the unseen/auto-popup case clears
// localStorage itself (see releaseNotes.test.ts) — that's the deliberate
// opt-in, not the default.
beforeEach(() => {
  markLatestReleaseSeen();
});

// Unmount any mounted React trees after each test to avoid cross-test bleed.
afterEach(() => {
  cleanup();
});
