# ADR 0037: The iOS app holds its refresh token in the Keychain and presents it in a header

**Status:** Accepted
**Date:** 2026-09-24

MysteryMixClub-kw2u. Builds on ADR 0032 (the real web app in the Capacitor
shell) and restores ADR 0034's logout guarantees on iOS.

## Context

The web session is an in-memory access token (60 minutes) plus a refresh token
in an HttpOnly, `SameSite=Lax` cookie (technical design §5). The iOS app runs
that same web app in a WKWebView whose origin is `capacitor://localhost`, which
is cross-site to the API. `Lax` withholds the cookie on every cross-site POST,
so it never reached `/auth/refresh` or `/auth/logout` from the phone. Staging
logs from a real device on 2026-09-20 showed it: `/auth/refresh` 401 every
time, and a logout that returned 200 but invalidated nothing. So on iOS:

1. a session lasted only as long as the access token: after an hour, or any
   relaunch, the member had to sign in again;
2. logout never revoked the session, whose refresh token stayed valid for 30
   days;
3. ADR 0034's server-side guarantees (logout deletes the session's push
   devices; a late registration after logout is refused) did not hold, because
   logout finds its session through that cookie.

Three options were on the table:

- **A. `SameSite=None; Secure` for the refresh cookie.** The smallest change,
  but it weakens the web's CSRF posture for every user to fix one client, and
  WKWebView's tracking prevention can still drop a third-party cookie, so it
  might not even work reliably.
- **B. The app holds the refresh token itself** and sends it explicitly. The
  standard pattern for native clients, but it needs a native plugin plus
  backend changes.
- **C. Logout identifies the session from the access token's `sid` claim**
  when no refresh token arrives. Restores revocation cheaply, but does nothing
  for session restore.

## Decision

**B, with C as a safety net.** The web is unchanged.

- **Sign-in returns the refresh token in the body, for the iOS app only.**
  Every JSON sign-in (`/auth/verify`, `/auth/login`, `/auth/register`,
  `/auth/google/native-exchange`, `/auth/apple/native-verify`) adds
  `refresh_token` to its response when the request's `Origin` is exactly
  `capacitor://localhost`, and omits the field otherwise. The cookie is still
  set either way. The gate is `Origin` because a browser sets it and page
  script cannot, so no web page, even one running injected script, can obtain
  a long-lived refresh token from a response body.
- **The app keeps it in the Keychain.** `MMCSessionStorePlugin`
  (`SessionStorePlugin.swift`) holds one item,
  `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: not synced to iCloud
  Keychain or restored from a backup to another device, but readable when the
  app launches in the background. `src/ios/sessionStore.ts` wraps it, and every
  call is best-effort.
- **It goes back in `X-Refresh-Token`.** `/auth/refresh`, `/auth/logout` and
  `/auth/logout-all` read the cookie first, then that header. A custom header
  cannot be sent cross-site without a CORS preflight, so it adds no CSRF
  surface.
- **Logout falls back to the Bearer access token's `sid`** when no refresh
  token arrives at all (a lost Keychain item, or a build from before this
  change). This only ever ends the session the token already belongs to. Only
  a valid, unexpired token counts.
- The app clears its saved token on logout, whatever the outcome, and when a
  refresh is rejected with a 401. Any other failure (offline, a 5xx) keeps it
  for the next try.

## Consequences

- iOS members stay signed in across relaunches for the full 30-day refresh
  window, and logout on iOS now revokes the session and, through ADR 0034's
  existing path, deletes its devices.
- On iOS the refresh token is readable by JS, briefly: it passes through the
  WebView on its way to and from the Keychain. Script injected into the app's
  WebView could read it; on the web, an HttpOnly cookie is out of script's
  reach. Such script could already act as the member with the access token, so
  the added exposure is persistence (30 days rather than 60 minutes), not
  capability. The app loads only its own bundled code, so this is accepted.
- Refresh tokens are still not rotated, same as on the web. A leaked Keychain
  token stays valid until logout, logout-all, a password reset, or 30 days.
- Keychain items survive an app uninstall on iOS. A reinstall may find an old
  token: if that session is still live the member is simply signed in; if not,
  the first refresh gets a 401 and the token is cleared.
- Backend endpoints take the refresh token from two places (cookie, then
  header). Anything new that needs the session must accept both.
- Proving it end to end needs a real iPhone (`kw2u`'s acceptance criteria):
  close and reopen the app and stay signed in; log out and the session is
  revoked. Backend tests and an HTTP-level check against the local API cover
  the server side; the simulator build compiles the plugin.

## Revisit if

- Capacitor's iOS origin changes (a custom `iosScheme` or `hostname` in
  `capacitor.config.ts`): `_NATIVE_APP_ORIGIN` in `auth.py` must match it, or
  sign-ins stop returning the token.
- The app ever loads remote or third-party script into its WebView, which
  would make the JS-readable token a real exposure.
- Refresh-token rotation is adopted for the web; the native path should rotate
  the same way.
