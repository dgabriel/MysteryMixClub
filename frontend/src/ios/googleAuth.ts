import { Capacitor, registerPlugin } from "@capacitor/core";

export type GoogleSignInResult = {
  outcome: string;
  code: string;
};

interface NativeGoogleAuthPlugin {
  signIn(options: { apiBaseUrl: string; inviteToken?: string }): Promise<GoogleSignInResult>;
}

export const nativeGoogleAuthAvailable = () =>
  Capacitor.getPlatform() === "ios" && Capacitor.isPluginAvailable("MMCGoogleAuth");

export const googleAuth = registerPlugin<NativeGoogleAuthPlugin>("MMCGoogleAuth");
