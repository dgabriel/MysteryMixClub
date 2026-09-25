import { Capacitor, registerPlugin } from "@capacitor/core";

/** Opens this app's notification settings in iOS Settings (MysteryMixClub-gxh3):
 *  the only way back after someone has denied push. */
interface NativeAppSettingsPlugin {
  openNotificationSettings(): Promise<void>;
}

// Registered on first use, not at import (see ios/sessionStore.ts).
let plugin: NativeAppSettingsPlugin | null = null;

/** Resolves true if Settings opened. Never throws. */
export async function openNotificationSettings(): Promise<boolean> {
  if (Capacitor.getPlatform() !== "ios" || !Capacitor.isPluginAvailable("MMCAppSettings")) {
    return false;
  }
  try {
    plugin ??= registerPlugin<NativeAppSettingsPlugin>("MMCAppSettings");
    await plugin.openNotificationSettings();
    return true;
  } catch {
    return false;
  }
}
