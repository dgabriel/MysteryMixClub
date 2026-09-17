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

/** Requests the OS permission prompt and, if granted, registers for remote
 *  notifications. iOS only ever shows the real system prompt once —a second
 *  call after a denial silently resolves "denied" again rather than
 *  re-prompting, which is exactly why the manual explainer path exists
 *  alongside this (it can't undo a denial; only Settings can). Safe to call
 *  repeatedly otherwise. */
export async function requestPushPermissionAndRegister(): Promise<PushPermissionStatus> {
  const status = await PushNotifications.requestPermissions();
  if (status.receive !== "granted") {
    return status.receive === "denied" ? "denied" : "prompt";
  }
  await PushNotifications.register();
  return "granted";
}

/** Wires the plugin's registration/tap listeners once at app startup.
 *  `onDeepLink` receives the {club_id, mix_id, event} custom data payload
 *  (MysteryMixClub-4vii.26's own push data shape) when the user taps a
 *  notification, in any app state (foreground/background/terminated). */
export function initializePushListeners(onDeepLink: (data: Record<string, string>) => void): void {
  PushNotifications.addListener("registration", (token) => {
    storeDeviceToken(token.value);
    void registerPushToken(token.value);
  });
  PushNotifications.addListener("registrationError", () => {
    // Best-effort: nothing actionable to show the user for a registration
    // failure, and there's no user-visible "retry" for something that
    // happens silently in the background -- same degradation as the
    // backend being unconfigured (no push this session, nothing else
    // breaks).
  });
  PushNotifications.addListener("pushNotificationActionPerformed", (action: ActionPerformed) => {
    const data = action.notification.data as Record<string, string> | undefined;
    if (data) onDeepLink(data);
  });
}

/** Tells the backend to drop this device's registration (called on logout,
 *  PRD IOS-04: "remove account associations on logout or deletion"). A
 *  no-op if this device never registered (no stored token). */
export async function unregisterCurrentDevice(): Promise<void> {
  const token = currentDeviceToken();
  if (token) {
    await unregisterPushToken(token);
  }
}
