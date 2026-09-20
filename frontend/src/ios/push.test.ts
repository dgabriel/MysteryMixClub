import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getPlatformMock = vi.fn();
vi.mock("@capacitor/core", () => ({
  Capacitor: { getPlatform: (...args: unknown[]) => getPlatformMock(...args) },
}));

const checkPermissionsMock = vi.fn();
const requestPermissionsMock = vi.fn();
const registerMock = vi.fn();
const addListenerMock = vi.fn();
vi.mock("@capacitor/push-notifications", () => ({
  PushNotifications: {
    checkPermissions: (...args: unknown[]) => checkPermissionsMock(...args),
    requestPermissions: (...args: unknown[]) => requestPermissionsMock(...args),
    register: (...args: unknown[]) => registerMock(...args),
    addListener: (...args: unknown[]) => addListenerMock(...args),
  },
}));

const appAddListenerMock = vi.fn();
vi.mock("@capacitor/app", () => ({
  App: { addListener: (...args: unknown[]) => appAddListenerMock(...args) },
}));

const registerPushTokenMock = vi.fn();
const unregisterPushTokenMock = vi.fn();
vi.mock("../services/api", () => ({
  registerPushToken: (...args: unknown[]) => registerPushTokenMock(...args),
  unregisterPushToken: (...args: unknown[]) => unregisterPushTokenMock(...args),
}));

type Handler = (payload: never) => void;
let nativeHandlers: Record<string, Handler>;

/** Fresh module state (registration state, session epoch, attached listeners)
 *  for every test -- push.ts keeps all of it at module level. */
async function loadPush({ open = true }: { open?: boolean } = {}) {
  vi.resetModules();
  const push = await import("./push");
  // AuthProvider opens the push session when a signed-in session begins.
  if (open) push.openPushSession();
  return push;
}

/** Lets pending promise continuations run without advancing any timer. */
const settle = () => vi.advanceTimersByTimeAsync(0);

function emitToken(value: string) {
  (nativeHandlers.registration as (t: { value: string }) => void)({ value: value });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  localStorage.clear();
  nativeHandlers = {};
  getPlatformMock.mockReturnValue("ios");
  checkPermissionsMock.mockResolvedValue({ receive: "granted" });
  registerMock.mockResolvedValue(undefined);
  registerPushTokenMock.mockResolvedValue(undefined);
  unregisterPushTokenMock.mockResolvedValue(undefined);
  addListenerMock.mockImplementation((event: string, handler: Handler) => {
    nativeHandlers[event] = handler;
    return Promise.resolve({ remove: vi.fn() });
  });
  appAddListenerMock.mockResolvedValue({ remove: vi.fn().mockResolvedValue(undefined) });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("nativePushAvailable (MysteryMixClub-4vii.27, IOS-04)", () => {
  it("is true only on iOS, matching googleAuth/appleAuth's own convention", async () => {
    const { nativePushAvailable } = await loadPush();

    getPlatformMock.mockReturnValue("ios");
    expect(nativePushAvailable()).toBe(true);

    getPlatformMock.mockReturnValue("web");
    expect(nativePushAvailable()).toBe(false);
  });
});

describe("pushPermissionStatus", () => {
  it("maps the plugin's receive field onto the three-state type", async () => {
    const { pushPermissionStatus } = await loadPush();

    checkPermissionsMock.mockResolvedValue({ receive: "granted" });
    expect(await pushPermissionStatus()).toBe("granted");

    checkPermissionsMock.mockResolvedValue({ receive: "denied" });
    expect(await pushPermissionStatus()).toBe("denied");

    checkPermissionsMock.mockResolvedValue({ receive: "prompt" });
    expect(await pushPermissionStatus()).toBe("prompt");

    checkPermissionsMock.mockResolvedValue({ receive: "prompt-with-rationale" });
    expect(await pushPermissionStatus()).toBe("prompt");
  });
});

describe("syncPushRegistration (MysteryMixClub-4vii.32)", () => {
  it("with permission already granted, captures the native token, uploads it, and only then reports registered", async () => {
    const { syncPushRegistration, getPushRegistrationState } = await loadPush();

    const done = syncPushRegistration();
    await settle();
    expect(registerMock).toHaveBeenCalledOnce();
    // register() has resolved but the native token has not arrived: not done.
    expect(getPushRegistrationState()).toBe("registering");
    expect(registerPushTokenMock).not.toHaveBeenCalled();

    emitToken("device-token-abc");
    expect(await done).toBe("registered");

    expect(registerPushTokenMock).toHaveBeenCalledWith("device-token-abc");
    expect(getPushRegistrationState()).toBe("registered");
    expect(localStorage.getItem("mmcDevicePushToken")).toBe("device-token-abc");
  });

  it("never prompts and never registers when permission is not granted", async () => {
    const { syncPushRegistration, getPushRegistrationState } = await loadPush();

    for (const receive of ["prompt", "denied"]) {
      checkPermissionsMock.mockResolvedValue({ receive });
      expect(await syncPushRegistration()).toBe("idle");
    }

    expect(requestPermissionsMock).not.toHaveBeenCalled();
    expect(registerMock).not.toHaveBeenCalled();
    expect(registerPushTokenMock).not.toHaveBeenCalled();
    expect(getPushRegistrationState()).toBe("idle");
  });

  it("is a no-op off native iOS", async () => {
    getPlatformMock.mockReturnValue("web");
    const { syncPushRegistration } = await loadPush();

    expect(await syncPushRegistration()).toBe("idle");

    expect(checkPermissionsMock).not.toHaveBeenCalled();
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("reports failed, not registered, when the backend rejects the upload -- and a retry can succeed", async () => {
    const { syncPushRegistration, getPushRegistrationState } = await loadPush();
    registerPushTokenMock.mockRejectedValueOnce(new Error("HTTP 503"));

    const first = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    expect(await first).toBe("failed");
    expect(getPushRegistrationState()).toBe("failed");
    // Remembered from the moment the upload was sent, so logout can still ask
    // the backend to drop whatever row a lost or timed-out request left behind.
    expect(localStorage.getItem("mmcDevicePushToken")).toBe("device-token-abc");

    const retry = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    expect(await retry).toBe("registered");
    expect(registerPushTokenMock).toHaveBeenCalledTimes(2);
  });

  it("reports failed when the native side reports a registration error", async () => {
    const { syncPushRegistration } = await loadPush();

    const done = syncPushRegistration();
    await settle();
    (nativeHandlers.registrationError as (e: { error: string }) => void)({ error: "no network" });

    expect(await done).toBe("failed");
    expect(registerPushTokenMock).not.toHaveBeenCalled();
  });

  it("reports failed when the native token never arrives", async () => {
    const { syncPushRegistration } = await loadPush();

    const done = syncPushRegistration();
    await vi.advanceTimersByTimeAsync(15_000);

    expect(await done).toBe("failed");
    expect(registerPushTokenMock).not.toHaveBeenCalled();
  });

  it("reports failed when the upload hangs", async () => {
    const { syncPushRegistration } = await loadPush();
    registerPushTokenMock.mockReturnValue(new Promise(() => {}));

    const done = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await vi.advanceTimersByTimeAsync(15_000);

    expect(await done).toBe("failed");
  });

  it("reports failed when register() itself throws, without leaving a token wait behind", async () => {
    const { syncPushRegistration } = await loadPush();
    registerMock.mockRejectedValueOnce(new Error("native bridge down"));

    expect(await syncPushRegistration()).toBe("failed");

    // A later attempt still works: nothing stale is waiting on the next token.
    const retry = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    expect(await retry).toBe("registered");
    expect(registerPushTokenMock).toHaveBeenCalledOnce();
  });

  it("shares one attempt between concurrent callers", async () => {
    const { syncPushRegistration } = await loadPush();

    const a = syncPushRegistration();
    const b = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");

    expect(await a).toBe("registered");
    expect(await b).toBe("registered");
    expect(registerMock).toHaveBeenCalledOnce();
    expect(registerPushTokenMock).toHaveBeenCalledOnce();
  });

  it("does not re-register a device that is already registered", async () => {
    const { syncPushRegistration } = await loadPush();
    const first = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await first;

    expect(await syncPushRegistration()).toBe("registered");

    expect(registerMock).toHaveBeenCalledOnce();
  });

  it("drops a stale 'registered' once permission is withdrawn in iOS Settings", async () => {
    const { syncPushRegistration, getPushRegistrationState } = await loadPush();
    const first = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await first;

    checkPermissionsMock.mockResolvedValue({ receive: "denied" });
    await syncPushRegistration();

    expect(getPushRegistrationState()).toBe("idle");
  });

  it("attaches the native listeners once, however many attempts run", async () => {
    const { syncPushRegistration } = await loadPush();

    for (let attempt = 0; attempt < 3; attempt += 1) {
      registerPushTokenMock.mockRejectedValueOnce(new Error("offline"));
      const done = syncPushRegistration();
      await settle();
      emitToken("device-token-abc");
      await done;
    }

    // registration + registrationError + notification-tap, exactly once each.
    expect(addListenerMock).toHaveBeenCalledTimes(3);
  });

  it("does not upload a token that arrives after the session was invalidated (logout or account switch)", async () => {
    const { syncPushRegistration, invalidatePushSession, getPushRegistrationState } =
      await loadPush();

    const done = syncPushRegistration();
    await settle();
    invalidatePushSession(); // e.g. the account signed out while the OS minted the token
    emitToken("device-token-abc");
    await done;

    expect(registerPushTokenMock).not.toHaveBeenCalled();
    expect(getPushRegistrationState()).toBe("idle");
    expect(localStorage.getItem("mmcDevicePushToken")).toBeNull();
  });

  it("an abandoned attempt cannot overwrite the next account's state", async () => {
    const {
      syncPushRegistration,
      invalidatePushSession,
      openPushSession,
      getPushRegistrationState,
    } = await loadPush();

    const first = syncPushRegistration(); // account A
    await settle();
    invalidatePushSession(); // account A leaves...
    openPushSession(); // ...and account B's session begins
    const second = syncPushRegistration();
    await settle();
    emitToken("device-token-abc"); // resolves whoever is waiting
    await Promise.all([first, second]);

    // Only the current session's attempt uploads and reports.
    expect(registerPushTokenMock).toHaveBeenCalledOnce();
    expect(getPushRegistrationState()).toBe("registered");
  });
});

describe("requestPushPermissionAndRegister", () => {
  it("starts registering the device once the OS prompt is granted, without making the caller wait for it", async () => {
    const { requestPushPermissionAndRegister, getPushRegistrationState } = await loadPush();
    requestPermissionsMock.mockResolvedValue({ receive: "granted" });

    const status = await requestPushPermissionAndRegister();

    expect(status).toBe("granted");
    // Resolved on the permission alone; the registration is still under way.
    expect(getPushRegistrationState()).toBe("registering");
    await settle();
    expect(registerMock).toHaveBeenCalledOnce();
    emitToken("device-token-abc");
    await settle();
    expect(registerPushTokenMock).toHaveBeenCalledWith("device-token-abc");
    expect(getPushRegistrationState()).toBe("registered");
  });

  it("never calls register() when the OS prompt is denied", async () => {
    const { requestPushPermissionAndRegister } = await loadPush();
    requestPermissionsMock.mockResolvedValue({ receive: "denied" });

    const status = await requestPushPermissionAndRegister();

    expect(status).toBe("denied");
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("leaves a registration failure observable rather than throwing", async () => {
    const { requestPushPermissionAndRegister, getPushRegistrationState } = await loadPush();
    requestPermissionsMock.mockResolvedValue({ receive: "granted" });
    registerPushTokenMock.mockRejectedValue(new Error("HTTP 500"));

    expect(await requestPushPermissionAndRegister()).toBe("granted");
    await settle();
    emitToken("device-token-abc");
    await settle();

    expect(getPushRegistrationState()).toBe("failed");
  });

  it("does not register if the session ended while the OS prompt was on screen", async () => {
    const { requestPushPermissionAndRegister, invalidatePushSession } = await loadPush();
    let answerPrompt: (r: { receive: string }) => void = () => {};
    requestPermissionsMock.mockReturnValue(
      new Promise((resolve) => {
        answerPrompt = resolve;
      }),
    );

    const pending = requestPushPermissionAndRegister();
    invalidatePushSession(); // logged out while the prompt was up
    answerPrompt({ receive: "granted" });

    expect(await pending).toBe("granted"); // the permission is still the phone's
    await settle();
    expect(registerMock).not.toHaveBeenCalled();
  });
});

describe("initializePushListeners", () => {
  it("routes a tapped notification's data payload to the deep-link callback", async () => {
    const { initializePushListeners } = await loadPush();
    const onDeepLink = vi.fn();
    initializePushListeners(onDeepLink);
    await settle();

    (
      nativeHandlers.pushNotificationActionPerformed as (a: {
        notification: { data?: Record<string, string> };
      }) => void
    )({ notification: { data: { club_id: "club-1", event: "voting_opened" } } });

    expect(onDeepLink).toHaveBeenCalledWith({ club_id: "club-1", event: "voting_opened" });
  });

  it("does not throw and does not deep-link when a tapped notification carries no data", async () => {
    const { initializePushListeners } = await loadPush();
    const onDeepLink = vi.fn();
    initializePushListeners(onDeepLink);
    await settle();

    const handler = nativeHandlers.pushNotificationActionPerformed as (a: {
      notification: { data?: Record<string, string> };
    }) => void;

    expect(() => handler({ notification: {} })).not.toThrow();
    expect(onDeepLink).not.toHaveBeenCalled();
  });

  it("attaches listeners once even when called repeatedly, using the latest callback", async () => {
    const { initializePushListeners } = await loadPush();
    const first = vi.fn();
    const second = vi.fn();

    initializePushListeners(first);
    initializePushListeners(second);
    await settle();
    (
      nativeHandlers.pushNotificationActionPerformed as (a: {
        notification: { data?: Record<string, string> };
      }) => void
    )({ notification: { data: { club_id: "club-1" } } });

    expect(addListenerMock).toHaveBeenCalledTimes(3);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });

  it("ignores a token event nobody asked for rather than uploading it", async () => {
    const { initializePushListeners } = await loadPush();
    initializePushListeners(vi.fn());
    await settle();

    emitToken("unsolicited-token");

    expect(registerPushTokenMock).not.toHaveBeenCalled();
  });
});

describe("onAppResume", () => {
  it("calls back only when the app becomes active, and stops after unsubscribe", async () => {
    const { onAppResume } = await loadPush();
    const remove = vi.fn().mockResolvedValue(undefined);
    let onStateChange: (s: { isActive: boolean }) => void = () => {};
    appAddListenerMock.mockImplementation(
      (_event: string, handler: (s: { isActive: boolean }) => void) => {
        onStateChange = handler;
        return Promise.resolve({ remove });
      },
    );
    const callback = vi.fn();

    const stop = onAppResume(callback);
    await settle();
    onStateChange({ isActive: false });
    expect(callback).not.toHaveBeenCalled();
    onStateChange({ isActive: true });
    expect(callback).toHaveBeenCalledOnce();

    stop();
    await settle();
    expect(remove).toHaveBeenCalledOnce();
  });

  it("removes a listener that finished attaching only after the caller already unsubscribed", async () => {
    const { onAppResume } = await loadPush();
    const remove = vi.fn().mockResolvedValue(undefined);
    let attach: (h: { remove: () => Promise<void> }) => void = () => {};
    appAddListenerMock.mockReturnValue(
      new Promise((resolve) => {
        attach = resolve;
      }),
    );

    const stop = onAppResume(vi.fn());
    stop();
    attach({ remove });
    await settle();

    expect(remove).toHaveBeenCalledOnce();
  });

  it("is a no-op off native iOS", async () => {
    getPlatformMock.mockReturnValue("web");
    const { onAppResume } = await loadPush();

    onAppResume(vi.fn())();

    expect(appAddListenerMock).not.toHaveBeenCalled();
  });
});

describe("registration state store", () => {
  it("notifies subscribers on change only, and stops after unsubscribe", async () => {
    const {
      subscribePushRegistration,
      invalidatePushSession,
      openPushSession,
      syncPushRegistration,
    } = await loadPush();
    const notify = vi.fn();
    const unsubscribe = subscribePushRegistration(notify);

    invalidatePushSession(); // idle -> idle: not a change
    expect(notify).not.toHaveBeenCalled();
    openPushSession();

    const done = syncPushRegistration();
    await settle();
    expect(notify).toHaveBeenCalledOnce(); // idle -> registering
    emitToken("device-token-abc");
    await done;
    expect(notify).toHaveBeenCalledTimes(2); // registering -> registered

    unsubscribe();
    invalidatePushSession();
    expect(notify).toHaveBeenCalledTimes(2);
  });
});

describe("unregisterCurrentDevice", () => {
  it("tells the backend to drop the stored device token, and forgets it locally", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    const registered = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await registered;

    await unregisterCurrentDevice();

    expect(unregisterPushTokenMock).toHaveBeenCalledWith("device-token-abc");
    expect(localStorage.getItem("mmcDevicePushToken")).toBeNull();
  });

  it("is a no-op when this device never registered", async () => {
    const { unregisterCurrentDevice } = await loadPush();

    await unregisterCurrentDevice();

    expect(unregisterPushTokenMock).not.toHaveBeenCalled();
  });

  it("resets the registration state so a signed-out device never reads as registered", async () => {
    const { syncPushRegistration, unregisterCurrentDevice, getPushRegistrationState } =
      await loadPush();
    const registered = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await registered;

    await unregisterCurrentDevice();

    expect(getPushRegistrationState()).toBe("idle");
  });

  it("waits for an upload already in flight, so the row it creates is removed too", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    let finishUpload: () => void = () => {};
    registerPushTokenMock.mockReturnValue(
      new Promise<void>((resolve) => {
        finishUpload = resolve;
      }),
    );

    const registering = syncPushRegistration();
    await settle();
    emitToken("device-token-abc"); // upload now in flight
    await settle();
    const loggingOut = unregisterCurrentDevice(); // logout lands mid-upload
    await settle();
    expect(unregisterPushTokenMock).not.toHaveBeenCalled(); // still waiting on the upload

    finishUpload();
    await Promise.all([registering, loggingOut]);

    expect(unregisterPushTokenMock).toHaveBeenCalledWith("device-token-abc");
    expect(localStorage.getItem("mmcDevicePushToken")).toBeNull();
  });

  it("stops waiting on a stuck attempt after a bounded time", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    registerPushTokenMock.mockReturnValue(new Promise(() => {}));
    void syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await settle();

    const loggingOut = unregisterCurrentDevice();
    await vi.advanceTimersByTimeAsync(5_000);

    await expect(loggingOut).resolves.toBeUndefined();
  });
});

describe("the session gate and epoch capture (MysteryMixClub-4vii.32)", () => {
  it("does nothing while no session is open, without even checking permission", async () => {
    const { syncPushRegistration, registerCurrentDevice } = await loadPush({ open: false });

    expect(await syncPushRegistration()).toBe("idle");
    expect(await registerCurrentDevice()).toBe("idle");

    expect(checkPermissionsMock).not.toHaveBeenCalled();
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("logout closes the gate: a foreground sync during the logout window cannot register the leaving account", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();

    const loggingOut = unregisterCurrentDevice(); // AuthProvider's effect is still live here
    const duringLogout = syncPushRegistration(); // e.g. an app-resume event
    await loggingOut;

    expect(await duringLogout).toBe("idle");
    expect(registerMock).not.toHaveBeenCalled();
    expect(registerPushTokenMock).not.toHaveBeenCalled();
  });

  it("a sync that was waiting on the permission check when the session ended never registers, even if the next session has opened", async () => {
    const { syncPushRegistration, invalidatePushSession, openPushSession } = await loadPush();
    let answerCheck: (r: { receive: string }) => void = () => {};
    checkPermissionsMock.mockReturnValue(
      new Promise((resolve) => {
        answerCheck = resolve;
      }),
    );

    const stale = syncPushRegistration(); // account A
    invalidatePushSession();
    openPushSession(); // account B's session is already open
    answerCheck({ receive: "granted" });

    expect(await stale).toBe("idle");
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("registers again once a new session opens", async () => {
    const { syncPushRegistration, invalidatePushSession, openPushSession } = await loadPush();
    invalidatePushSession();
    openPushSession();

    const done = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");

    expect(await done).toBe("registered");
  });

  it("reports failed, with a way to retry, when the permission check itself throws", async () => {
    const { syncPushRegistration, getPushRegistrationState } = await loadPush();
    checkPermissionsMock.mockRejectedValueOnce(new Error("native bridge down"));

    await syncPushRegistration();

    expect(getPushRegistrationState()).toBe("failed");
    const retry = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    expect(await retry).toBe("registered");
  });

  it("reports failed when register() itself never returns", async () => {
    const { syncPushRegistration } = await loadPush();
    registerMock.mockReturnValue(new Promise(() => {}));

    const done = syncPushRegistration();
    await vi.advanceTimersByTimeAsync(15_000);

    expect(await done).toBe("failed");
  });

  it("re-attaches only the native listener that failed to attach, never a duplicate of the others", async () => {
    const { syncPushRegistration } = await loadPush();
    let failNextErrorListener = true;
    addListenerMock.mockImplementation((event: string, handler: Handler) => {
      if (event === "registrationError" && failNextErrorListener) {
        failNextErrorListener = false;
        return Promise.reject(new Error("bridge hiccup"));
      }
      nativeHandlers[event] = handler;
      return Promise.resolve({ remove: vi.fn() });
    });

    expect(await syncPushRegistration()).toBe("failed"); // could not attach
    const retry = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    expect(await retry).toBe("registered");

    const attachedEvents = addListenerMock.mock.calls.map((c) => c[0] as string);
    expect(attachedEvents.filter((e) => e === "registration")).toHaveLength(1);
    expect(attachedEvents.filter((e) => e === "pushNotificationActionPerformed")).toHaveLength(1);
    expect(attachedEvents.filter((e) => e === "registrationError")).toHaveLength(2);
  });
});

describe("unregisterCurrentDevice cleanup guarantees (MysteryMixClub-4vii.32)", () => {
  it("does not make logout wait for an attempt that is only waiting on the OS", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    void syncPushRegistration();
    await settle(); // register() called; no token yet, so nothing has been uploaded

    let finished = false;
    void unregisterCurrentDevice().then(() => {
      finished = true;
    });
    await settle();

    expect(finished).toBe(true); // did not sit out the 5s settle window
  });

  it("still cleans up after an upload that timed out client-side but may have landed", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    registerPushTokenMock.mockReturnValue(new Promise(() => {})); // never answers
    const registering = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await vi.advanceTimersByTimeAsync(15_000);
    expect(await registering).toBe("failed");

    await unregisterCurrentDevice();

    expect(unregisterPushTokenMock).toHaveBeenCalledWith("device-token-abc");
  });

  it("keeps the token and reports the failure when the backend cannot remove the registration", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    const registering = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await registering;
    unregisterPushTokenMock.mockRejectedValueOnce(new Error("offline"));

    await expect(unregisterCurrentDevice()).rejects.toThrow("offline");

    // Not forgotten: a later cleanup can still try to remove it.
    expect(localStorage.getItem("mmcDevicePushToken")).toBe("device-token-abc");
  });

  it("never logs the device token when cleanup fails", async () => {
    const { syncPushRegistration, unregisterCurrentDevice } = await loadPush();
    const registering = syncPushRegistration();
    await settle();
    emitToken("device-token-abc");
    await registering;
    unregisterPushTokenMock.mockRejectedValueOnce(new Error("offline"));

    await unregisterCurrentDevice().catch(() => {});

    const logged = JSON.stringify(vi.mocked(console.error).mock.calls);
    expect(logged).not.toContain("device-token-abc");
    expect(logged).toContain("push unregister failed");
  });
});
