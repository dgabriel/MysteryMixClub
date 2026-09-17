import { beforeEach, describe, expect, it, vi } from "vitest";

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

const registerPushTokenMock = vi.fn();
const unregisterPushTokenMock = vi.fn();
vi.mock("../services/api", () => ({
  registerPushToken: (...args: unknown[]) => registerPushTokenMock(...args),
  unregisterPushToken: (...args: unknown[]) => unregisterPushTokenMock(...args),
}));

// localStorage isn't reset between tests by jsdom automatically.
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("nativePushAvailable (MysteryMixClub-4vii.27, IOS-04)", () => {
  it("is true only on iOS, matching googleAuth/appleAuth's own convention", async () => {
    const { nativePushAvailable } = await import("./push");

    getPlatformMock.mockReturnValue("ios");
    expect(nativePushAvailable()).toBe(true);

    getPlatformMock.mockReturnValue("web");
    expect(nativePushAvailable()).toBe(false);
  });
});

describe("pushPermissionStatus", () => {
  it("maps the plugin's receive field onto the three-state type", async () => {
    const { pushPermissionStatus } = await import("./push");

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

describe("requestPushPermissionAndRegister", () => {
  it("registers with the plugin only once the OS prompt is granted", async () => {
    const { requestPushPermissionAndRegister } = await import("./push");
    requestPermissionsMock.mockResolvedValue({ receive: "granted" });

    const status = await requestPushPermissionAndRegister();

    expect(status).toBe("granted");
    expect(registerMock).toHaveBeenCalledOnce();
  });

  it("never calls register() when the OS prompt is denied", async () => {
    const { requestPushPermissionAndRegister } = await import("./push");
    requestPermissionsMock.mockResolvedValue({ receive: "denied" });

    const status = await requestPushPermissionAndRegister();

    expect(status).toBe("denied");
    expect(registerMock).not.toHaveBeenCalled();
  });
});

describe("initializePushListeners", () => {
  it("persists the device token and forwards it to the backend on 'registration'", async () => {
    const { initializePushListeners } = await import("./push");
    initializePushListeners(vi.fn());

    const handler = addListenerMock.mock.calls.find((c) => c[0] === "registration")?.[1] as (t: {
      value: string;
    }) => void;
    handler({ value: "device-token-abc" });

    expect(registerPushTokenMock).toHaveBeenCalledWith("device-token-abc");
    expect(localStorage.getItem("mmcDevicePushToken")).toBe("device-token-abc");
  });

  it("routes a tapped notification's data payload to the deep-link callback", async () => {
    const { initializePushListeners } = await import("./push");
    const onDeepLink = vi.fn();
    initializePushListeners(onDeepLink);

    const handler = addListenerMock.mock.calls.find(
      (c) => c[0] === "pushNotificationActionPerformed",
    )?.[1] as (a: { notification: { data?: Record<string, string> } }) => void;
    handler({ notification: { data: { club_id: "club-1", event: "voting_opened" } } });

    expect(onDeepLink).toHaveBeenCalledWith({ club_id: "club-1", event: "voting_opened" });
  });

  it("does not throw and does not deep-link when a tapped notification carries no data", async () => {
    const { initializePushListeners } = await import("./push");
    const onDeepLink = vi.fn();
    initializePushListeners(onDeepLink);

    const handler = addListenerMock.mock.calls.find(
      (c) => c[0] === "pushNotificationActionPerformed",
    )?.[1] as (a: { notification: { data?: Record<string, string> } }) => void;

    expect(() => handler({ notification: {} })).not.toThrow();
    expect(onDeepLink).not.toHaveBeenCalled();
  });
});

describe("unregisterCurrentDevice", () => {
  it("tells the backend to drop the stored device token", async () => {
    const { initializePushListeners, unregisterCurrentDevice } = await import("./push");
    initializePushListeners(vi.fn());
    const handler = addListenerMock.mock.calls.find((c) => c[0] === "registration")?.[1] as (t: {
      value: string;
    }) => void;
    handler({ value: "device-token-abc" });

    await unregisterCurrentDevice();

    expect(unregisterPushTokenMock).toHaveBeenCalledWith("device-token-abc");
  });

  it("is a no-op when this device never registered", async () => {
    const { unregisterCurrentDevice } = await import("./push");

    await unregisterCurrentDevice();

    expect(unregisterPushTokenMock).not.toHaveBeenCalled();
  });
});
