/** Resolves and validates the iOS release build's API base URL. Extracted
 *  out of vite.ios.config.ts (which can't be exercised by vitest -- it isn't
 *  under src/**) so the fail-closed HTTPS check has real test coverage.
 *
 *  Throws rather than falling back: the iOS build carries no ATS local-
 *  networking exception (MysteryMixClub-4vii.12), so a non-HTTPS backend is
 *  unreachable by construction, and a build that "succeeded" against one
 *  would just fail invisibly on-device instead of at build time. */
export interface IosBuildContext {
  /** The MMC_APP_DOMAIN Xcode build setting (MysteryMixClub-4vii.52):
   *  staging.mysterymixclub.com for Debug, mysterymixclub.com for Release, so
   *  an archive (TestFlight / App Store) talks to prod. Also drives the
   *  universal-links domain in App.entitlements. */
  appDomain?: string;
  localSimulator?: string;
  configuration?: string;
  platform?: string;
  action?: string;
}

export function resolveIosApiBaseUrl(
  envValue: string | undefined,
  context: IosBuildContext = {},
): string {
  if (context.localSimulator !== undefined) {
    if (
      context.localSimulator !== "1" ||
      context.configuration !== "Debug" ||
      context.platform !== "iphonesimulator" ||
      context.action !== "build"
    ) {
      throw new Error(
        "Local API access requires an explicit Debug iphonesimulator build (not an archive).",
      );
    }
    const url = new URL(envValue ?? "http://localhost:8000");
    if (
      url.protocol !== "http:" ||
      !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash
    ) {
      throw new Error(
        "Local simulator API must be a loopback HTTP origin without credentials, path, query, or fragment.",
      );
    }
    return url.origin;
  }
  if (envValue === undefined && context.appDomain !== undefined) {
    // A bare hostname only: this becomes the origin, so anything else (a
    // scheme, a path, a port) is a misconfigured build setting.
    if (
      !/^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/.test(context.appDomain)
    ) {
      throw new Error(`MMC_APP_DOMAIN must be a bare hostname, got "${context.appDomain}".`);
    }
    return `https://${context.appDomain}`;
  }
  const apiBaseUrl = envValue ?? "https://staging.mysterymixclub.com";
  if (!apiBaseUrl.startsWith("https://")) {
    throw new Error(
      `VITE_IOS_API_BASE_URL must be an https:// URL, got "${apiBaseUrl}". ` +
        "The iOS build has no local-network ATS exception, so a non-HTTPS backend is unreachable " +
        "by design (MysteryMixClub-4vii.12) -- this is not a build worth completing.",
    );
  }
  return apiBaseUrl;
}
