/**
 * Whether the app can reach its API (MysteryMixClub-ga4y). A plain module
 * store rather than React state, because the API client (not React) is what
 * notices a failed request, and the auth provider needs to await reconnection
 * outside render.
 *
 * Offline means either the browser says so (`navigator.onLine`, the
 * online/offline events) or a request just failed at the network level, which
 * also covers "on wifi, but no internet". Coming back is confirmed by a real
 * request: the API client's health probe, retried every few seconds while
 * offline, or any request that gets a response.
 */

const PROBE_INTERVAL_MS = 5000;
/** How long "back online" shows before the app carries on. */
export const RECONNECTED_MS = 1500;

export type ConnectivityPhase = "online" | "offline" | "reconnected";

let browserOffline = typeof navigator !== "undefined" ? !navigator.onLine : false;
let requestFailed = false;
let probe: (() => Promise<boolean>) | null = null;
let probeTimer: ReturnType<typeof setInterval> | null = null;
let reconnectedTimer: ReturnType<typeof setTimeout> | null = null;
let wasOffline = browserOffline;
const listeners = new Set<() => void>();
const backOnlineListeners = new Set<() => void>();

export function isOffline(): boolean {
  return browserOffline || requestFailed;
}

/** "reconnected" for RECONNECTED_MS after coming back, then "online". */
export function getConnectivityPhase(): ConnectivityPhase {
  if (isOffline()) return "offline";
  return reconnectedTimer !== null ? "reconnected" : "online";
}

function notify(): void {
  const offline = isOffline();
  if (offline) {
    if (reconnectedTimer !== null) {
      clearTimeout(reconnectedTimer);
      reconnectedTimer = null;
    }
  } else if (wasOffline) {
    reconnectedTimer = setTimeout(() => {
      reconnectedTimer = null;
      for (const listener of listeners) listener();
      for (const listener of backOnlineListeners) listener();
    }, RECONNECTED_MS);
  }
  wasOffline = offline;
  for (const listener of listeners) listener();
}

/** Runs when "back online" has shown and the app should reload stale data. */
export function onBackOnline(listener: () => void): () => void {
  backOnlineListeners.add(listener);
  return () => backOnlineListeners.delete(listener);
}

export function subscribeConnectivity(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The API client's way to check the server is reachable again. */
export function setConnectivityProbe(fn: () => Promise<boolean>): void {
  probe = fn;
}

function stopProbing(): void {
  if (probeTimer !== null) {
    clearInterval(probeTimer);
    probeTimer = null;
  }
}

async function runProbe(): Promise<void> {
  if (!probe || browserOffline) return;
  if (await probe()) reportNetworkSuccess();
}

function startProbing(): void {
  if (probeTimer !== null) return;
  probeTimer = setInterval(() => void runProbe(), PROBE_INTERVAL_MS);
}

/** A request failed before any response came back. */
export function reportNetworkFailure(): void {
  startProbing();
  if (requestFailed) return;
  requestFailed = true;
  notify();
}

/** A request got a response, so the API is reachable. */
export function reportNetworkSuccess(): void {
  stopProbing();
  if (!requestFailed) return;
  requestFailed = false;
  notify();
}

/** Resolves once the app is back online (immediately if it already is). */
export function waitUntilOnline(): Promise<void> {
  if (!isOffline()) return Promise.resolve();
  return new Promise((resolve) => {
    const unsubscribe = subscribeConnectivity(() => {
      if (!isOffline()) {
        unsubscribe();
        resolve();
      }
    });
  });
}

if (typeof window !== "undefined") {
  window.addEventListener("offline", () => {
    browserOffline = true;
    notify();
  });
  window.addEventListener("online", () => {
    browserOffline = false;
    notify();
    // The browser has a network again; confirm the API itself answers.
    if (requestFailed) void runProbe();
  });
}

/** Test-only: restore the initial state. */
export function resetConnectivityForTests(): void {
  stopProbing();
  if (reconnectedTimer !== null) clearTimeout(reconnectedTimer);
  reconnectedTimer = null;
  browserOffline = false;
  requestFailed = false;
  wasOffline = false;
  probe = null;
  listeners.clear();
  backOnlineListeners.clear();
}
