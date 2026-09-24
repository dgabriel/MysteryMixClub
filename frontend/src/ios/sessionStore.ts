import { Capacitor, registerPlugin } from "@capacitor/core";

/**
 * The iOS app's Keychain-held refresh token (MysteryMixClub-kw2u, ADR 0037).
 * On web the refresh token is an HttpOnly cookie JS never sees; this WebView's
 * origin never gets that cookie back, so the native build holds the token here
 * and sends it in the `X-Refresh-Token` header instead.
 *
 * Every call is best-effort: a Keychain failure must never break sign-in or
 * logout. The worst case is the pre-fix behaviour (sign in again), and logout
 * still revokes through the access token's session.
 */
interface NativeSessionStorePlugin {
  getRefreshToken(): Promise<{ token: string | null }>;
  setRefreshToken(options: { token: string }): Promise<void>;
  clearRefreshToken(): Promise<void>;
}

// Registered on first use, not at import: api.ts imports this module, and
// registering at load would reach into @capacitor/core for every consumer of
// the API client (including tests that stub Capacitor without it).
let plugin: NativeSessionStorePlugin | null = null;
function sessionStore(): NativeSessionStorePlugin {
  plugin ??= registerPlugin<NativeSessionStorePlugin>("MMCSessionStore");
  return plugin;
}

function available(): boolean {
  return Capacitor.getPlatform() === "ios" && Capacitor.isPluginAvailable("MMCSessionStore");
}

function logFailure(action: string, error: unknown): void {
  // Never log the token itself; the plugin's error carries only a code.
  console.error(`session store ${action} failed`, error instanceof Error ? error.message : error);
}

export async function loadRefreshToken(): Promise<string | null> {
  if (!available()) return null;
  try {
    return (await sessionStore().getRefreshToken()).token;
  } catch (error) {
    logFailure("read", error);
    return null;
  }
}

export async function saveRefreshToken(token: string): Promise<void> {
  if (!available()) return;
  try {
    await sessionStore().setRefreshToken({ token });
  } catch (error) {
    logFailure("write", error);
  }
}

export async function clearRefreshToken(): Promise<void> {
  if (!available()) return;
  try {
    await sessionStore().clearRefreshToken();
  } catch (error) {
    logFailure("clear", error);
  }
}
