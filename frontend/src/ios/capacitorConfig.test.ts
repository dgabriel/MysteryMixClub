import { describe, expect, it } from "vitest";
import config from "../../capacitor.config";
import packageJson from "../../package.json?raw";
import xcodeProject from "../../ios/App/App.xcodeproj/project.pbxproj?raw";

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

// The phone reads ios/App/App/capacitor.config.json, which is generated
// (gitignored, absent in CI) from the source config above by `cap sync`. That
// file cannot be asserted on here, so this guards the chain that produces it:
// the sync script, and the Xcode build phase that runs it before every build.
describe("the sync chain that carries the config to the phone (MysteryMixClub-4vii.34)", () => {
  it("ios:sync runs `cap sync ios`, which regenerates the native config from the source", () => {
    const scripts = (JSON.parse(packageJson) as { scripts: Record<string, string> }).scripts;
    expect(scripts["ios:sync"]).toContain("cap sync ios");
  });

  it("the Xcode project runs `npm run ios:sync` on every build rather than reusing a stale bundle", () => {
    expect(xcodeProject).toContain("npm run ios:sync");
    // Without this Xcode skips the phase when it thinks nothing changed.
    expect(xcodeProject).toContain("alwaysOutOfDate = 1");
  });
});
