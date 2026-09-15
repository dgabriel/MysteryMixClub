/** Resolves and validates the iOS release build's API base URL. Extracted
 *  out of vite.ios.config.ts (which can't be exercised by vitest -- it isn't
 *  under src/**) so the fail-closed HTTPS check has real test coverage.
 *
 *  Throws rather than falling back: the iOS build carries no ATS local-
 *  networking exception (MysteryMixClub-4vii.12), so a non-HTTPS backend is
 *  unreachable by construction, and a build that "succeeded" against one
 *  would just fail invisibly on-device instead of at build time. */
export function resolveIosApiBaseUrl(envValue: string | undefined): string {
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
