import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import { PushNotifications, type ActionPerformed } from "@capacitor/push-notifications";
import { registerPushToken, unregisterPushToken } from "../services/api";

export const nativePushAvailable = () => Capacitor.getPlatform() === "ios";

/** Persisted so a logout in a later launch (not the one that registered)
 *  can still tell the backend which token to drop -- there's no API to read
 *  a device's current APNs token back from the OS, only the one-time
 *  'registration' event when register() completes. */
const DEVICE_TOKEN_STORAGE_KEY = "mmcDevicePushToken";

function storeDeviceToken(token: string): void {
  try {
    localStorage.setItem(DEVICE_TOKEN_STORAGE_KEY, token);
  } catch {
    // Private browsing / storage disabled -- registration itself already
    // reached the backend; only the logout-cleanup convenience is lost.
  }
}

function currentDeviceToken(): string | null {
  try {
    return localStorage.getItem(DEVICE_TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

function clearDeviceToken(): void {
  try {
    localStorage.removeItem(DEVICE_TOKEN_STORAGE_KEY);
  } catch {
    // Nothing to clear if storage is unavailable.
  }
}

export type PushPermissionStatus = "granted" | "denied" | "prompt";

/** Whether the OS permission prompt has already been shown and answered --
 *  drives the choice between auto-prompting and showing the manual "enable
 *  notifications" explainer (MysteryMixClub-4vii.27: both paths exist;
 *  this is what tells the caller which one applies). */
export async function pushPermissionStatus(): Promise<PushPermissionStatus> {
  const status = await PushNotifications.checkPermissions();
  if (status.receive === "granted") return "granted";
  if (status.receive === "denied") return "denied";
  return "prompt";
}

// --------------------------------------------------------------------------
// Registration (MysteryMixClub-4vii.32)
//
// OS permission and "the backend can reach this device" are different facts.
// Permission is a property of the phone and survives logout; the backend
// registration belongs to a signed-in account, is dropped on logout, and can
// silently fail (native token never arrives, upload rejected, offline). So
// registration is tracked as its own state and is only reported as done once
// BOTH the native token was captured AND the authenticated upload succeeded.
// --------------------------------------------------------------------------

/** idle: nothing to report (not attempted, no permission, or signed out).
 *  registering: an attempt is in flight. registered: the backend accepted this
 *  device's token for the signed-in account. failed: the last attempt did not
 *  complete; retryable. */
export type PushRegistrationState = "idle" | "registering" | "registered" | "failed";

/** register() resolves before the native token event, so the token is awaited
 *  separately; both waits are bounded so a missing callback or a hung upload
 *  ends in "failed" (retryable) rather than a spinner that never resolves. */
const NATIVE_TOKEN_TIMEOUT_MS = 15_000;
const UPLOAD_TIMEOUT_MS = 15_000;
/** How long logout waits for an in-flight registration to settle before
 *  dropping the device's association. */
const LOGOUT_SETTLE_TIMEOUT_MS = 5_000;

let registrationState: PushRegistrationState = "idle";
const registrationSubscribers = new Set<() => void>();

function setRegistrationState(next: PushRegistrationState): void {
  if (next === registrationState) return;
  registrationState = next;
  registrationSubscribers.forEach((notify) => notify());
}

export function getPushRegistrationState(): PushRegistrationState {
  return registrationState;
}

/** For `useSyncExternalStore`. Returns the unsubscribe function. */
export function subscribePushRegistration(notify: () => void): () => void {
  registrationSubscribers.add(notify);
  return () => {
    registrationSubscribers.delete(notify);
  };
}

/** Bumped whenever the signed-in identity may have changed (logout, account
 *  switch). A registration attempt remembers the epoch it began in and gives
 *  up -- no upload, no state change -- if the epoch moved on, so a callback
 *  that lands late can never attach this device to the wrong account. */
let sessionEpoch = 0;
/** Registration is only allowed while a signed-in session is open. Closed at
 *  module start and by `invalidatePushSession` (logout, account change), and
 *  reopened by `openPushSession` -- so nothing that runs during the moments
 *  around a logout can start a fresh attempt for the account that is leaving. */
let sessionOpen = false;

/** Each native listener is attached once per process. Tracked per event (not as
 *  one all-or-nothing promise) so a failure attaching one of them is retried
 *  on the next attempt without re-adding the ones that already attached. */
const listenerAttachments = new Map<string, Promise<void>>();
let deepLinkHandler: ((data: Record<string, string>) => void) | null = null;

type TokenWaiter = { resolve: (token: string) => void; reject: (error: Error) => void };
const tokenWaiters = new Set<TokenWaiter>();

function attachOnce(event: string, attach: () => Promise<unknown>): Promise<void> {
  const existing = listenerAttachments.get(event);
  if (existing) return existing;
  const attached = attach().then(
    () => undefined,
    (error: unknown) => {
      listenerAttachments.delete(event);
      throw error;
    },
  );
  listenerAttachments.set(event, attached);
  return attached;
}

async function ensureNativeListeners(): Promise<void> {
  await Promise.all([
    attachOnce("registration", () =>
      PushNotifications.addListener("registration", (token) => {
        tokenWaiters.forEach((waiter) => waiter.resolve(token.value));
      }),
    ),
    attachOnce("registrationError", () =>
      PushNotifications.addListener("registrationError", (failure) => {
        // No token in this payload. Logged because a native failure has no
        // Network-tab equivalent -- this is the only place the reason surfaces.
        console.error("push native registration failed", failure.error);
        tokenWaiters.forEach((waiter) => waiter.reject(new Error("native registration failed")));
      }),
    ),
    attachOnce("pushNotificationActionPerformed", () =>
      PushNotifications.addListener(
        "pushNotificationActionPerformed",
        (action: ActionPerformed) => {
          const data = action.notification.data as Record<string, string> | undefined;
          if (data) deepLinkHandler?.(data);
        },
      ),
    ),
  ]);
}

/** Resolves with the next native device token, rejects on a native error or on
 *  timeout. `cancel` drops the wait when register() itself throws. */
function nextDeviceToken(): { token: Promise<string>; cancel: () => void } {
  let cancel = () => {};
  const token = new Promise<string>((resolve, reject) => {
    const timer = setTimeout(
      () => finish(() => reject(new Error("timed out waiting for the device token"))),
      NATIVE_TOKEN_TIMEOUT_MS,
    );
    const waiter: TokenWaiter = {
      resolve: (value) => finish(() => resolve(value)),
      reject: (error) => finish(() => reject(error)),
    };
    function finish(settle: () => void): void {
      clearTimeout(timer);
      tokenWaiters.delete(waiter);
      settle();
    }
    cancel = () => finish(() => reject(new Error("cancelled")));
    tokenWaiters.add(waiter);
  });
  return { token, cancel };
}

function withTimeout<T>(work: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${what} timed out`)), ms);
    work.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error instanceof Error ? error : new Error(`${what} failed`));
      },
    );
  });
}

/** The most recent attempt, kept after it settles until replaced so logout can
 *  wait for one that is mid-upload. */
type Attempt = {
  epoch: number;
  promise: Promise<void>;
  running: boolean;
  /** True once the token upload has been sent: from then on a row may exist
   *  server-side even if this attempt is abandoned, so logout must wait for it. */
  uploading: boolean;
};
let latestAttempt: Attempt | null = null;

async function performRegistration(attempt: Attempt): Promise<void> {
  await ensureNativeListeners();
  const wait = nextDeviceToken();
  // If register() throws first, nobody awaits `wait.token`; keep its eventual
  // rejection from surfacing as an unhandled one.
  wait.token.catch(() => {});
  try {
    await withTimeout(PushNotifications.register(), NATIVE_TOKEN_TIMEOUT_MS, "push register");
  } catch (error) {
    wait.cancel();
    throw error;
  }
  const token = await wait.token;
  // The account may have changed while the OS was minting the token.
  if (attempt.epoch !== sessionEpoch) return;
  // Remembered from the moment the upload is sent, not after it succeeds: a
  // request that times out client-side can still land server-side, and logout
  // needs the token to remove whatever row that leaves behind.
  storeDeviceToken(token);
  attempt.uploading = true;
  await withTimeout(registerPushToken(token), UPLOAD_TIMEOUT_MS, "push token upload");
}

/** Captures this device's APNs token and registers it with the backend for the
 *  signed-in account. Concurrent calls in the same session share one attempt.
 *  Never throws: the outcome is the returned/observable state, and "failed" is
 *  always retryable. Does NOT request OS permission -- callers decide that. */
export function registerCurrentDevice(): Promise<PushRegistrationState> {
  if (!nativePushAvailable() || !sessionOpen) return Promise.resolve("idle");
  const epoch = sessionEpoch;
  if (latestAttempt?.running && latestAttempt.epoch === epoch) {
    return latestAttempt.promise.then(() => registrationState);
  }
  setRegistrationState("registering");
  const attempt: Attempt = { epoch, running: true, uploading: false, promise: Promise.resolve() };
  attempt.promise = (async () => {
    try {
      await performRegistration(attempt);
      if (epoch === sessionEpoch) setRegistrationState("registered");
    } catch (error) {
      console.error(
        "push registration failed",
        error instanceof Error ? error.message : "unknown error",
      );
      if (epoch === sessionEpoch) setRegistrationState("failed");
    } finally {
      attempt.running = false;
    }
  })();
  latestAttempt = attempt;
  return attempt.promise.then(() => (epoch === sessionEpoch ? registrationState : "idle"));
}

/** Reconciles this device with the backend for the signed-in account: if OS
 *  permission is already granted and the device is not yet registered, register
 *  it. Idempotent, never prompts, and a no-op unless permission is granted --
 *  safe to call after every login/session restore and every return from
 *  Settings (MysteryMixClub-4vii.32). */
export async function syncPushRegistration(): Promise<PushRegistrationState> {
  if (!nativePushAvailable() || !sessionOpen) return "idle";
  // Captured before the first await: whatever this call goes on to do belongs
  // to the session that asked, and is dropped if that session ends meanwhile.
  const epoch = sessionEpoch;
  let permission: PushPermissionStatus;
  try {
    permission = await pushPermissionStatus();
  } catch (error) {
    console.error(
      "push permission check failed",
      error instanceof Error ? error.message : "unknown error",
    );
    // Could not tell whether registration is possible: say so (retryable)
    // rather than leaving a spinner-like "connecting" state with no way out.
    if (epoch === sessionEpoch && !latestAttempt?.running) setRegistrationState("failed");
    return epoch === sessionEpoch ? registrationState : "idle";
  }
  if (epoch !== sessionEpoch || !sessionOpen) return "idle";
  if (permission !== "granted") {
    // Permission was withdrawn or never given: nothing to register, and a
    // stale "registered" must not linger.
    if (!latestAttempt?.running) setRegistrationState("idle");
    return "idle";
  }
  if (registrationState === "registered") return registrationState;
  return registerCurrentDevice();
}

/** Marks that the signed-in identity may have changed. Any attempt still
 *  waiting on the OS is abandoned before it uploads, and the state resets. */
export function invalidatePushSession(): void {
  sessionEpoch += 1;
  sessionOpen = false;
  setRegistrationState("idle");
}

/** Allows registration for the session that is now signed in. Called when a
 *  session begins (login, restore, account change) and undone by
 *  `invalidatePushSession` when it ends. */
export function openPushSession(): void {
  sessionOpen = true;
}

/** Calls `callback` each time the app returns to the foreground -- the moment
 *  a user comes back from iOS Settings having changed notification permission.
 *  Returns the unsubscribe function; a no-op off native iOS. */
export function onAppResume(callback: () => void): () => void {
  if (!nativePushAvailable()) return () => {};
  let removed = false;
  let handle: { remove: () => Promise<void> } | undefined;
  void App.addListener("appStateChange", ({ isActive }) => {
    if (isActive) callback();
  }).then((added) => {
    if (removed) void added.remove();
    else handle = added;
  });
  return () => {
    removed = true;
    void handle?.remove();
  };
}

/** Requests the OS permission prompt and, if granted, starts registering this
 *  device with the backend. iOS only ever shows the real system prompt once --
 *  a second call after a denial silently resolves "denied" again rather than
 *  re-prompting, which is exactly why the manual explainer path exists
 *  alongside this (it can't undo a denial; only Settings can). Resolves with
 *  the permission as soon as it is known; the registration's outcome is
 *  observable through `getPushRegistrationState`. */
export async function requestPushPermissionAndRegister(): Promise<PushPermissionStatus> {
  const epoch = sessionEpoch;
  const status = await PushNotifications.requestPermissions();
  if (status.receive !== "granted") {
    return status.receive === "denied" ? "denied" : "prompt";
  }
  // The prompt can sit on screen a long time; if the session ended meanwhile,
  // the permission is still the phone's, but registering is not this call's job.
  if (epoch === sessionEpoch) {
    // Deliberately not awaited: the outcome is the observable registration
    // state, and the caller's button should not stay busy through both waits.
    void registerCurrentDevice();
  }
  return "granted";
}

/** Wires the notification-tap listener (and the registration listeners) once at
 *  app startup; safe to call more than once -- listeners are attached a single
 *  time and only the latest `onDeepLink` is used. `onDeepLink` receives the
 *  {club_id, mix_id, event} custom data payload (MysteryMixClub-4vii.26's own
 *  push data shape) when the user taps a notification, in any app state
 *  (foreground/background/terminated). */
export function initializePushListeners(onDeepLink: (data: Record<string, string>) => void): void {
  deepLinkHandler = onDeepLink;
  void ensureNativeListeners().catch(() => {
    // Attached again by the next registration attempt.
  });
}

/** Tells the backend to drop this device's registration (called on logout,
 *  PRD IOS-04: "remove account associations on logout or deletion"). Ends any
 *  in-progress registration first so it cannot re-attach the device to the
 *  account that is signing out. A no-op if this device never registered. */
export async function unregisterCurrentDevice(): Promise<void> {
  invalidatePushSession();
  // Only an attempt that has already sent its upload can leave a row behind;
  // one still waiting on the OS is abandoned by the epoch change and needs no
  // waiting for.
  const pending = latestAttempt?.running && latestAttempt.uploading ? latestAttempt.promise : null;
  if (pending) {
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, LOGOUT_SETTLE_TIMEOUT_MS);
      void pending.then(() => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
  const token = currentDeviceToken();
  if (!token) return;
  try {
    await unregisterPushToken(token);
  } catch (error) {
    // Kept in storage so a later cleanup can retry it; the caller still logs
    // out. Nothing but the failure's own message is logged, never the token.
    console.error(
      "push unregister failed",
      error instanceof Error ? error.message : "unknown error",
    );
    throw error;
  }
  clearDeviceToken();
}
