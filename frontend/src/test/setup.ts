import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Unmount any mounted React trees after each test to avoid cross-test bleed.
afterEach(() => {
  cleanup();
});
