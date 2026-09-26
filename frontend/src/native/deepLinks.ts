import { App } from "@capacitor/app";
import { IS_NATIVE_BUILD } from "../lib/platform";

type MinimalRouter = { navigate: (to: string) => void };

/**
 * Routes a Universal Link tap (magic-link email, Google OAuth's redirect
 * landing page, a club invite link) into the already-running native app
 * instead of Safari (MysteryMixClub-4vii.10).
 *
 * Universal Links, not a custom URL scheme: the backend emits one ordinary
 * https:// link for every recipient regardless of platform (auth.py's
 * app_base_url), and it must keep working unchanged for the vast majority of
 * members who don't have the native app installed. A custom scheme would
 * need its own non-https link that fails outright without the app; a
 * Universal Link degrades to a normal page load in Safari when the app
 * isn't installed or the target domain's apple-app-site-association doesn't
 * match, and opens in-app when it does -- no email/backend fork needed.
 *
 * Requires the Associated Domains entitlement (App.entitlements) and a
 * matching apple-app-site-association hosted on the target domain; this is
 * inert without both. No-op on web -- browsers already navigate normally.
 */
export function registerDeepLinkHandler(router: MinimalRouter): void {
  if (!IS_NATIVE_BUILD) return;

  App.addListener("appUrlOpen", ({ url }) => {
    let target: URL;
    try {
      target = new URL(url);
    } catch {
      // A malformed URL from the OS isn't something the app caused; drop it
      // rather than crash the whole native shell over one bad deep link.
      return;
    }
    router.navigate(`${target.pathname}${target.search}`);
  });
}
