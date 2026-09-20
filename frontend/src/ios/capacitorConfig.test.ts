import { describe, expect, it } from "vitest";
import config from "../../capacitor.config";

describe("capacitor.config (MysteryMixClub-4vii.34)", () => {
  it("shows a push that arrives while the app is open as a system banner in Notification Center", () => {
    // Without this the native plugin returns no presentation options and iOS
    // silently drops a foreground push.
    expect(config.plugins?.PushNotifications?.presentationOptions).toEqual(["banner", "list"]);
  });

  it("does not use the iOS-deprecated 'alert', nor add sound or a badge the backend never sends", () => {
    const options = config.plugins?.PushNotifications?.presentationOptions ?? [];
    expect(options).not.toContain("alert");
    expect(options).not.toContain("sound");
    expect(options).not.toContain("badge");
  });
});
