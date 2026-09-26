import { Capacitor, registerPlugin } from "@capacitor/core";

export type AppleSignInResult =
  | { outcome: "ok"; identityToken: string }
  | { outcome: "cancelled"; identityToken?: undefined };

interface NativeAppleAuthPlugin {
  signIn(): Promise<AppleSignInResult>;
}

export const nativeAppleAuthAvailable = () =>
  Capacitor.getPlatform() === "ios" && Capacitor.isPluginAvailable("MMCAppleAuth");

export const appleAuth = registerPlugin<NativeAppleAuthPlugin>("MMCAppleAuth");
