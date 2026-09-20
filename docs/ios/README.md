# Getting started with the iOS proof

The [PRD](PRD-v0.1.md) is the supplied draft, preserved unchanged. [ADR 0028](../adr/0028-prototype-ios-with-capacitor-and-native-musickit.md) records the prototype architecture and [ADR 0029](../adr/0029-native-owns-the-http-boundary-in-the-ios-proof.md) records why the server calls are made from Swift rather than from the WebView. Durable progress lives in Bead `MysteryMixClub-yyuq`.

## The tools in plain language

React continues to draw MMC's screens. Capacitor packages those screens in an iPhone application and lets JavaScript call native code. Swift is the language for the Apple Music integration and, here, for the calls to the MMC backend. Xcode builds, signs, and runs the application. Signing associates a build with your Apple development team and permitted devices. TestFlight is a later beta-distribution step.

## This Mac's readiness

Confirmed on September 13, 2026:

- Xcode 26.6, with `xcode-select -p` pointing inside it. CocoaPods is not installed and is not needed: the project uses Swift Package Manager, the default for new Capacitor 8 iOS projects.
- A physical iPhone ("Dawn's iPhone", iPhone 16 Plus, iOS 26.6) paired through Xcode's Devices window.
- Apple ID `dgabriel@gmail.com` holds a paid Apple Developer Program membership, so MusicKit enrollment is not a blocker.
- An explicit (non-wildcard) App ID is registered for `com.mysterymixclub.app`. The auto-generated "XC Wildcard" App ID is not sufficient.

Both a simulator build and a signed device build currently succeed with no warnings from the app's own code.

**The deployment target is iOS 16.0.** Capacitor 8's floor is 15.0, but `MusicLibraryRequest` needs 16, and reading the playlist back out of the device library is central to the proof. This is a prototype-scoped choice. It is an input to the PRD's still-open "supported devices and OS" decision, not an answer to it.

## Running the proof on your iPhone

```
cd frontend
npm run ios:open     # open the project in Xcode
```

In Xcode, pick your iPhone as the run destination and press Run. The first run on a new device needs the device registered to the team, which selecting it as the destination does automatically.

**The web bundle syncs itself now (`MysteryMixClub-4vii.19`).** A build phase
named "Sync web bundle" runs `npm run ios:sync` automatically, first, before
every build or archive -- `npm run ios:sync` by hand is no longer required
(though still harmless if you run it anyway). It always runs (the phase's
"Based on dependency analysis" option is off) so a stale bundle is never
silently reused, and it fails the whole Xcode build if the sync fails (a
TypeScript error, for instance) rather than archiving old content.

This required disabling `ENABLE_USER_SCRIPT_SANDBOXING` project-wide: Xcode
15's script-phase sandbox otherwise blocks the sync from writing to
`ios/App/App/public`, `capacitor.config.json`, and `CapApp-SPM/Package.swift`
(`EPERM: operation not permitted`), and those writes are too spread across
the source tree for a narrow `outputPaths` declaration to unblock instead.
This is the standard, documented workaround for Capacitor/React-Native-style
sync phases; it only affects this one first-party script phase, not
third-party build tooling.

The build always points at a real HTTPS backend -- staging by default
(`vite.ios.config.ts`), overridable with `VITE_IOS_API_BASE_URL` for prod or
another target. There is no LAN/plain-HTTP option: a phone can't reach
`127.0.0.1` on your Mac anyway, and `Info.plist` carries no App Transport
Security relief to fall back on (removed in `MysteryMixClub-4vii.12` --
config resolving to anything but `https://` now fails the build outright
rather than shipping a build that could reach a real user with a
local-network permission prompt).

Since [ADR 0032](../adr/0032-run-the-real-web-app-inside-the-capacitor-shell.md),
most requests are made by the WebView via `frontend/src/services/api.ts`, not
by native `URLSession` -- that means CORS applies, and the target backend's
`ALLOWED_ORIGINS` must include `capacitor://localhost` (already true for
staging and prod; see `scripts/staging.env.example` / `scripts/prod.env.example`).

## Privacy manifest audit (`MysteryMixClub-4vii.17`, 2026-09-15)

Apple requires a `PrivacyInfo.xcprivacy` manifest for any linked framework
that uses a "Required Reason" API (file timestamps, disk space, system boot
time, or `UserDefaults`), and lists Capacitor among SDKs subject to this.
Audited and verified, not just inferred:

- Capacitor's own `Capacitor.xcframework` and `Cordova.xcframework` (pulled
  in via `capacitor-swift-pm`) already ship their own clean manifests
  (`NSPrivacyAccessedAPITypes` empty, `NSPrivacyTracking` false).
- `@capacitor/app`'s native Swift (`AppPlugin.swift`) uses only
  `NotificationCenter`, `UIApplication` state, and `Bundle.main` -- none of
  which are Required Reason APIs -- so it needs no manifest of its own.
- This app's own Swift (`MusicPlugin.swift`, `MMCAPIClient.swift`,
  `ProofViewController.swift`, `AppDelegate.swift`, `SceneDelegate.swift`)
  was grepped for the same API patterns: no matches.
- Confirmed end to end with a real `xcodebuild archive`: the build log shows
  Xcode's own privacy-manifest scan (`-scanforprivacyfile` against both
  frameworks) running as part of `builtin-infoPlistUtility`, and
  `-validate-for-store` passing. **ARCHIVE SUCCEEDED**, no privacy-manifest
  warnings or failures anywhere in the log.

**No `PrivacyInfo.xcprivacy` is needed for this app today.** Re-audit if a
new native plugin or dependency is added later -- particularly anything
touching `UserDefaults`, file metadata, or disk space, which would need its
own declared manifest at that point (never invent a reason merely to satisfy
validation; a reason must reflect actual use).

## What the proof does

1. **Sign in** to MMC with email and password. The access token stays in Swift; JavaScript never receives it.
2. **Connect Apple Music** through the native permission dialog, then report subscription eligibility, Sync Library state, and whether a native authorization token can be obtained. The token's value is never displayed, logged, or sent across the bridge.
3. **Build this mix's playlist** by calling the existing `POST /mixes/{id}/apple-playlist` with the native Music User Token. This is the compatibility question ADR 0028 left open.
4. **Check this mix** to reconcile both sides: what MMC recorded, and what this iPhone's library actually holds.
5. **Open Apple Music** at the member's library.

## What it deliberately does not claim

- **It offers no link to the playlist.** A library playlist URL does not resolve on a mobile client, confirmed twice on a real device including through the native `music://` scheme (`MysteryMixClub-o3r8`, `MysteryMixClub-ap25`). The proof gives the playlist's name and sends the member to their library instead.
- **Opening Apple Music is not evidence the member got there**, and the copy says so.
- **A build that did not answer is an unknown result, not a failure.** The proof blocks a second build until you reconcile, because retrying blind is how a member ends up with two playlists.
- **The track count is the server's confirmed count**, never the number submitted.

## Known session limitation

MMC's web session is an in-memory access token plus an HttpOnly refresh cookie. The native session keeps the refresh cookie in `URLSession`'s shared store, but the proof does not yet exercise a refresh, so a session lasts only as long as the 60-minute access token. Expiry recovery, account switching, and logout-all across devices are IOS-01 work and are not proven here.

## Tip jar via Apple IAP (`MysteryMixClub-4vii.15`, 2026-09-15)

The web app's Venmo tip link is gated out of the native build
(`nativeTipsAvailable()`) and replaced with three StoreKit consumables via a
new `MMCTipsPlugin.swift` -- an external payment link on iOS is a real
Guideline 3.1.1 risk. Tips unlock nothing (no club limits, votes,
submissions, or status change).

**This needs one manual App Store Connect step**: create three consumable
In-App Purchase products under this app's record, with exactly these
product ids (the plugin hardcodes them):

- `com.mysterymixclub.app.tip.small`
- `com.mysterymixclub.app.tip.medium`
- `com.mysterymixclub.app.tip.large`

Set whatever price tier and display name/description feel right for each
(the app renders StoreKit's own `displayName`/`displayPrice`, so whatever is
entered there is what shows).

**Deliberately deferred to a later version (`MysteryMixClub-4vii.23`):**
Apple requires the first consumable IAP of each type to be submitted bundled
with a new app version, not created and approved standalone
(https://developer.apple.com/help/app-store-connect/manage-submissions-to-app-review/submit-an-in-app-purchase).
Rather than couple the tip jar's App Review to the initial submission, the
IAP products were left unfinished/unsubmitted in App Store Connect for the
first release. This is a clean no-op, not a broken feature: until the
products exist and are approved, `getProducts()` returns an empty list and
the tip jar section on `/about` renders nothing at all (fails quietly by
design, same pattern Apple Music's own "unconfigured" state already uses) --
no tip jar and no Venmo link either (that's gated out specifically because
an external payment link is the Guideline 3.1.1 risk this feature exists to
avoid, so it's not a valid fallback). Nothing for App Review to reject in
the meantime. Finish the App Store Connect listings and bundle them with a
future version's submission per `MysteryMixClub-4vii.23` when ready.

## UGC moderation posture (`MysteryMixClub-4vii.13`, 2026-09-15)

App Store Guideline 1.2 requires a UGC app to offer a way to report
objectionable content. v1 is deliberately minimal: a member can report
another member's note (`POST /api/v1/reports`), which persists a row with
the reporter, the note's real author, the club, a reason, and optional
detail -- there is no admin console yet. Review it by querying the table
directly:

```sql
SELECT * FROM reports WHERE status = 'open' ORDER BY created_at DESC;
```

Mark a report reviewed with `UPDATE reports SET status = 'reviewed' WHERE
id = '<id>';` once handled (organizer member-removal, a direct conversation,
or no action needed). Blocking and automated content filtering were
deliberately deferred (basic report action only, not the full system) --
revisit if report volume or severity ever suggests they're needed.

## Native Google sign-in via ASWebAuthenticationSession (`MysteryMixClub-4vii.21`, 2026-09-15)

Google's OAuth policy blocks its own login page inside an embedded WebView
(`disallowed_useragent`, enforced since July 2023), which is what Capacitor's
`WKWebView` is. On top of that, Google's login screen (password + 2FA) can
take long enough for iOS to evict the app from memory during a cold-start
Universal Link handoff -- a known Capacitor gap
(`ionic-team/capacitor#6662`) where `appUrlOpen` doesn't reliably fire on
relaunch. Together these made the original web-style redirect flow
unworkable on native, independent of any deploy-pipeline correctness (see
the `.well-known` / `cp -r dist/.` fix below, which was a real but separate
bug).

The fix is `ASWebAuthenticationSession` (`GoogleAuthPlugin.swift`,
`MMCGoogleAuthPlugin`): it presents Google's login as a sheet on top of the
still-running app, so the app is never evicted, and Google accepts it as a
real browser context rather than an embedded WebView. It does **not**
require registering a custom URL scheme in `Info.plist`/`CFBundleURLTypes`
-- the bare scheme string (`mysterymixclub`, no `://`) is passed directly to
the session initializer, and `ASWebAuthenticationSession` intercepts the
callback itself.

Because the session's callback is only a captured URL with no shared cookie
jar guaranteed against the app's own `WKWebView`, the callback can't set the
session cookie directly the way the web flow does. Instead the backend
mints a short-lived (2 minute), single-use `OAuthExchangeCode` -- the exact
same pattern the existing magic-link flow already uses for its verification
token, not a new mechanism. `GET /google/login?native=true` carries a
`native` flag through the signed sign-in state; on success the callback
redirects to `mysterymixclub://auth/google?outcome=ok&code=<raw code>`
with **no cookie set on that response at all**. The app's own JS then
redeems the code from its own `WKWebView` context via
`POST /auth/google/native-exchange`, which hard-deletes the matching row on
lookup and only then sets the real refresh cookie -- guaranteeing the
session lands in the context that will actually use it.

Scope is deliberately narrow: only the sign-in flow moved. Google-account
*linking* from an already-authenticated Profile page stays on its old
web-only path (see the code comment in `google_callback`) -- broadening
that was not required for launch and would have widened this change
considerably.

`GoogleSignInButton` now renders either a real `<a href>` (web, since the
non-native endpoint still 302s and needs a top-level navigation) or a
`<button onClick>` (native) behind a discriminated union prop type -- same
Google-branded chrome either way, since only the interaction mechanism
differs.

## Sign in with Apple (`MysteryMixClub-4vii.9`, 2026-09-16)

App Store Guideline 4.8 requires an app offering a third-party/social login
(Google Sign-In, here) to also offer Sign in with Apple at equivalent
placement and prominence. `AppleAuthPlugin.swift` (`MMCAppleAuthPlugin`)
implements it via `ASAuthorizationController` -- structurally simpler than
the Google native fix (`MysteryMixClub-4vii.21`): Apple's own sign-in sheet
runs entirely inside the app with no browser hand-off, so there's no
redirect, state, nonce, PKCE, or one-time exchange code involved. The plugin
hands back a raw identity token; `POST /auth/apple/native-verify` verifies
its signature against Apple's public keys (`app.services.apple_signin`,
cached in-process, refetched on a cache miss or once a day) and resolves the
account.

**Requires the `.email` scope on the authorization request**
(`MysteryMixClub-4vii.24`, caught live during TestFlight testing): Apple only
includes an `email` claim in the identity token at all when the specific
request that produced it asked for the `.email` scope -- this is true on
*every* sign-in, not just the first, and applies whether the email is read
from `credential.email` or decoded from the identity token directly. Omitting
`requestedScopes` doesn't just skip the client-side convenience property, it
means the backend's `verify_apple_identity_token` always rejects the token
with "identity token carried no email" (401, generic "that sign-in didn't
work" shown to the user) -- indistinguishable from a real verification
failure without server-side log detail, which is what led to the fix in the
first place (`apple_native_sign_in`'s exception logging was previously
swallowing the specific `AppleSignInError` reason). `.fullName` is
deliberately still not requested -- MMC never uses the name Apple would
supply.

**This needs one manual Apple Developer Portal step before it works
on-device or in TestFlight**: enable the "Sign In with Apple" capability for
this app's App ID (`com.mysterymixclub.app`), then regenerate/re-download
its provisioning profile. `App.entitlements` already carries
`com.apple.developer.applesignin` -- without the portal capability enabled
to match, code signing with that entitlement present fails (or, in a
looser signing configuration, the capability silently does nothing
on-device). Same category of manual step as the IAP products above, just on
the Developer Portal rather than App Store Connect.

**Generalized identity model.** `AuthIdentity` (`auth_identities` table)
replaces per-provider columns on `User` for account resolution going
forward -- `User.google_id` is left in place (migration `07a9db76f961`
backfills it) since dropping a column outright isn't an additive migration
and MMC is live in prod, but every sign-in/link write now goes through
`AuthIdentity`, and the profile response's `google_linked`/`apple_linked`
both read from it.

**Identity-conflict hardening** (from the external review that raised
4vii.9): Apple's private relay ("Hide My Email") address is real and
Apple-verified, but proves nothing about who owns any *other* mailbox --
unlike a real Google/Apple email, it can never silently attach to an
existing account by email match. `_resolve_identity_account`'s
`allow_email_match` parameter is `False` whenever `is_private_email` is set,
so a relay-email sign-in either finds its own already-linked
`AuthIdentity` row, creates a brand-new invite-gated account, or -- if the
relay address happens to already be some other account's registered email
-- returns a clean 409 conflict rather than crashing on `users.email`'s
unique constraint or silently taking over that account. **Scope note:**
this hardening was NOT extended to Google's existing sign-in flow, which
still silently relinks a different Google identity onto an account when the
verified email matches (deliberate, tested behavior --
`test_existing_link_is_replaced_by_the_current_google_identity`). Reversing
that is a real product/security tradeoff with live-user lockout risk, not a
bug fix, so it's tracked separately rather than bundled in:
`MysteryMixClub-4vii.22`.

**Scope limitation:** Apple is native-iOS-only, matching where Guideline 4.8
actually applies -- there's no web `<a href>` equivalent (Sign in with
Apple's web flow needs its own JS SDK and redirect configuration this app
doesn't build) and no Settings-page "connect Apple" linking flow for an
already-authenticated user (mirrors Google's own account-link flow, but
wasn't required for launch). `apple_linked` on the profile response only
ever becomes `true` via signing in with Apple itself.

## Push notifications (`MysteryMixClub-4vii.25/26/27/28`, IOS-04)

Push reuses the official **`@capacitor/push-notifications` plugin** rather
than a custom Swift plugin like Google/Apple/Tips needed -- Capacitor ships
first-party APNs registration, permission, and token-capture support
already, so this needed only `AppDelegate.swift` boilerplate forwarding
`didRegisterForRemoteNotificationsWithDeviceToken`/
`didFailToRegisterForRemoteNotificationsWithError` into `NotificationCenter`
so the plugin's JS `'registration'`/`'registrationError'` events fire.

**APNs auth is token-based (`.p8` key)**, mirroring
`apple_music_token.py`'s exact ES256-JWT pattern (same library, same PEM
normalization, same in-process cache-with-refresh-margin, same
`is_configured` graceful-degradation gate) -- `apple_push_token.py` is close
enough to Apple Music's own service to have been copied structurally.
Unlike Apple Music's developer token, the provider-authentication token
carries no `exp` claim (Apple's guidance: mint it, reuse it under an hour,
re-mint rather than attach an expiry).

**The gateway is always production** (`api.push.apple.com`), never sandbox --
a decision, not an assumption: [ADR 0033](../adr/0033-apns-production-gateway-only.md).
It rests on **what the build is signed for**, which is not "Release vs Debug".
Per Apple's documentation, a device mints a *production* push token only when
the app is signed with a distribution provisioning profile (TestFlight, App
Store); one signed with a development profile mints a *sandbox* token that the
production gateway rejects (`BadDeviceToken`). `aps-environment` in `App.entitlements` is **not** what
ships: the signed value comes from the provisioning profile, so a checked-in
`production` coexists with a development-signed archive (observed: the local
`.xcarchive` files on this Mac are `Apple Development` identity,
`get-task-allow`, `aps-environment=development`). Those are pre-export
archives and say nothing about the build uploaded to TestFlight: Apple's
documented behaviour is that export re-signs for distribution with the
distribution profile, but that is not something these archives, or anything
checked here, demonstrate. Push is therefore tested with
TestFlight/App Store builds; an Xcode "Run" onto a device is a development
build and will not receive pushes from this backend. No environment toggle
exists. See "Which APNs environment is a build in?" below to verify a build.

**This needs two manual Apple Developer Portal steps before it works
on-device or in TestFlight**, both under Certificates, Identifiers &
Profiles: enable the **"Push Notifications" capability** for this app's App
ID (`com.mysterymixclub.app`) and regenerate/re-download its provisioning
profile (same category of step Sign in with Apple's own capability enable
needed, just a different capability), and create a **separate APNs
Authentication Key** (Keys → ＋ → check "Apple Push Notifications service
(APNs)") -- a different key from Apple Music's MusicKit key, even though
both reuse the same account-wide Team ID. `App.entitlements` already carries
`aps-environment=production`; without the portal capability enabled to
match, code signing with that entitlement present fails the same way Sign
in with Apple's entitlement does without its own capability enabled.
Provisioning walkthrough: `docs/staging-setup.md` → "Enabling push
notifications".

**Device tokens are per-device, not per-user.** `DevicePushToken` (one row
per registration, `device_token` unique) lets a user with several devices
receive the same event on each; `POST /users/me/push-token` upserts by
token (a token reassigns to whoever registers it, handling device reuse or
a different user signing into the same phone), `DELETE` scopes to the
caller's own rows. Account deletion drops the caller's tokens server-side;
logout drops the ones registered under that login session (see below).

**Two independent preferences**, `push_lifecycle_enabled` and
`push_deadline_reminders_enabled` (both default on), separate from each
other and from `email_notifications` -- the PRD's explicit requirement that
a user be able to turn off deadline nudges without losing lifecycle updates
or email entirely. Editable from Profile's "notification preferences"
section (`MysteryMixClub-4vii.28`); the two push toggles only render on
native iOS, since a toggle for a channel that can never deliver on web
would be confusing UI, not a neutral no-op.

**Dual reminder cadence** (`MysteryMixClub-4vii.26`, resolved from the
PRD's own open question: "confirm cadence before implementation" → both):
push sends at roughly 24 hours before a deadline (new, push-only, its own
`push_submission_reminder_sent_at`/`push_voting_reminder_sent_at` markers on
`Mix`) *and* at the existing 1-12-hour window email already uses (a new
push channel added alongside the existing warning, not a replacement).

**Permission timing is also both**, resolved the same way: an automatic OS
prompt fires once, right after onboarding completes, checked against
`pushPermissionStatus()` first so a user who already answered (denied or
granted) is never re-asked -- iOS only shows the real system dialog once
per app installation. Profile's notification-preferences section carries
the second path: a manual "enable notifications" explainer/button for
anyone who denied or dismissed the auto-prompt, or joined before it
existed. A denial can only be undone in iOS Settings, not by asking again
from inside the app -- the manual path explains that rather than pretending
a second in-app prompt would work.

**Registration is separate from permission, and follows the session**
(`MysteryMixClub-4vii.32`). OS permission belongs to the phone and survives
logout; the backend registration belongs to a signed-in account, is dropped on
logout, and can fail silently. So a device is only ever reported as
registered once the native token was captured **and** the authenticated
upload (`POST /users/me/push-token`) succeeded -- `register()` resolving
proves neither, since it returns before the token event. `AuthProvider`
reconciles after every login, every session restored from the cookie at
launch, and every return to the foreground (the way back from iOS Settings):
if permission is **already granted** and the device is not yet registered, it
registers. It never prompts -- the one-time OS prompt stays with onboarding
and Profile -- and it waits until onboarding is done. The state
(`idle | registering | registered | failed`, `ios/push.ts`) is what Profile
shows: "push is on for this device" only for `registered`, a plain "isn't
connected yet" with **try again** for `failed`. Nothing retries on a timer;
a failure is retried on the next foreground, the next login, or the button,
so attempts are bounded by the user. The `register()` call, the native-token
wait and the upload each time out after 15 seconds and end in `failed`, and
native listeners attach once per process, each tracked on its own, so a
partial failure is retried without duplicating the ones that attached.

**Which account a registration belongs to.** A push *session* is open exactly
while someone is signed in, keyed on the in-memory access token, so logout,
login, and a login that replaces a live session (a magic link opened while
another account is signed in) each end the old session and begin the next.
Registration is refused while no session is open, and every operation records
the session it started in *before* its first `await`: one from an earlier
session never uploads, however late its callback lands. Logout closes the
session first and then waits (up to 5 seconds) only for an upload that has
already been sent, so the row it may have created is usually removed too; the
token is remembered from the moment the upload is sent, so even a request that
timed out client-side can be cleaned up. None of that client work can undo an
upload the server has already accepted, so **the server enforces it**
([ADR 0034](../adr/0034-bind-push-registrations-to-the-login-session.md),
`MysteryMixClub-4vii.36`): the access token carries the login session it was
issued under (`sid`), a registration is only accepted from a live session, and
`/auth/logout` invalidates the session and deletes that session's device rows in
one transaction (`/auth/logout-all` and a password reset drop the account's
signed-out devices). An
upload that lands after logout is refused with a neutral 401, and an upload from
an older login cannot take a device back from a newer one (409). The client's
own `DELETE /users/me/push-token` stays as belt and braces; a failed one is
logged (the failure's message only, never the token), the token stays stored,
and logout still completes. The token, JWTs and payloads are never logged.
Known limits: a device row that already exists when this ships has no session,
so logout removes it only after the app re-registers and binds it (next launch
after the update), and a token minted before this shipped carries no session, so it can only
register new or unbound devices, never take one a session owns, until it expires
(at most an hour); a session that merely expires (30 days) is not swept.

**Token rotation** (`MysteryMixClub-4vii.37`). Apple documents that a device's
push token can change while the app is running, and the app is then told again.
Registration used to listen for that event only while an attempt was waiting for
its token, so a changed token was silently dropped and the backend kept the dead
one. Now a token event nobody asked for is handled: if this session has already
registered the device and the token differs from the one the backend accepted,
it is uploaded (same guards as a first registration: a live session and epoch,
a bounded upload, logout waits for it, the newest token is the one remembered
for logout). The registration state stays `registered` during the swap; a
failed upload makes it `failed`, which the next foreground or the Profile retry
recovers by asking the OS for the current token. Repeats of the same token are
ignored, several changes during one upload collapse to the newest, and an event
with no session, or for a device that never registered, is ignored. **The server
keeps one device token per login session**: registering a new token deletes the
token that session had before, in the same transaction, so the superseded one
does not linger (it is also deleted with the session on logout). Registrations of one session are serialized by a
row lock, so two racing registrations of different tokens cannot deadlock over
each other's rows; the last one wins. A client-timed-out upload is not aborted,
so if an old token's upload lands after the retry's, the server can hold the old
token until the next launch or login registers again (rare and bounded).

**Deep-linking.** A tapped notification (foreground, background, or
terminated) lands on the relevant club's home screen (`/clubs/:id`) --
deliberately not the specific mix's own detail page, matching
`notifications.py`'s own email CTA destination (`_club_url`) for the exact
same events, so a late or stale notification always opens somewhere
sensible even if the mix has since advanced past the state the notification
described.

**Foreground presentation** (`MysteryMixClub-4vii.34`). While the app is open
iOS does not show a push on its own: the plugin's native handler asks the app
how to present it, and with no `presentationOptions` configured it answered
"not at all", so the push arrived (the JS `pushNotificationReceived` event
fired) and nothing appeared. `frontend/capacitor.config.ts` now sets
`plugins.PushNotifications.presentationOptions` to `["banner", "list"]`: the
system banner, also kept in Notification Center. Deliberately no `sound` (the
person is already looking at the app) and no `badge` (the backend never sends a
count); `alert` is deprecated on iOS. No screen renders its own copy of the
notification, so it is not shown twice, and backgrounded/terminated delivery
and tap-to-open are unchanged. The value reaches the app through
`ios/App/App/capacitor.config.json`, which is **generated** (gitignored) by
`npm run ios:sync` -- and the Xcode "Sync web bundle" build phase runs that
before every build -- so a new build is what carries it to a phone. Foreground,
background and terminated behavior still has to be checked on a device; the
results are recorded in `MysteryMixClub-4vii.30`.

**Lock-screen copy is restrained**, matching the PRD's requirement: never
names a submitter, participation mode, or hidden result (e.g. "Voting is
open for The Mystery Mix Club", never "3 new songs to vote on").

**Invalid-token retirement** (`MysteryMixClub-4vii.33`). The response's
`reason` is read, not just its status. Only APNs' `410 Unregistered`, and
`400 BadDeviceToken` once this process has seen APNs accept the topic (APNs
checks the device token *before* the topic, and answers `BadDeviceToken` for
a token minted for the other environment too, so on its own it proves
nothing), delete the matching `DevicePushToken` row (its own fresh DB
session, since the background-task dispatch path may run after a
request-scoped session has already closed). The delete is scoped to the
exact `(token, user)` association that was sent to and to a row not
registered after the verdict (APNs' own `timestamp` on a 410), so a device
that re-registered, or a phone handed to another account, in the meantime
keeps its newer registration. Every other outcome -- a bad topic, `403`,
`429`, `5xx`, a network error, an unreadable body -- leaves the row alone and
is swallowed the same way `notifications._safe_send` treats one bad
recipient, so it never blocks the rest of a batch. Each rejected or retired
send logs its HTTP status and APNs reason at WARNING, and a skipped one (no
credentials, no topic) logs why (never a token, JWT or payload); the table in
`docs/staging-setup.md` → "Enabling push notifications" decodes them. **The
API's journal cannot show a successful send** -- it runs without INFO logging
outside development, so a missing `push send` line there means either APNs
accepted it or nothing was attempted (the deadline job's own unit does log
accepted sends at INFO) -- and a 200 is APNs' acceptance, not proof the phone
received anything. The `BadDeviceToken` gate is per process and proves the
topic and credentials, not the token's environment (a sandbox token is retired
like any other once a send has been accepted); why there is no environment handling is
[ADR 0033](../adr/0033-apns-production-gateway-only.md).

### Which APNs environment is a build in? (`MysteryMixClub-4vii.35`)

Four different facts get conflated here; each has its own check, and none
stands in for another:

| Question | How to know | What it does **not** prove |
|---|---|---|
| Is the **uploaded build** signed for production? | `scripts/ios-check-push-entitlement.sh <exported .ipa>` prints the signed `aps-environment` and the profile's. Run it on the `.ipa` Xcode exports, before uploading. | A `.xcarchive` is signed for development until export, so the script refuses to answer for one (exit 3). |
| Does **APNs accept our credentials**? | `backend/scripts/probe_apns_environment.py --check-credentials`, run on the Droplet with the runtime env loaded (command below). It sends a token that belongs to no device; a `BadDeviceToken` reply from the production gateway means Apple got past authenticating the provider (a bad key or Team ID is a `403` first). A key can be restricted to production only, so a sandbox `403` alone is reported as a note, not a failure. | Minting a JWT locally (the `staging-setup.md` "config sanity" step) proves only that the key can sign. It does not validate the topic either: APNs checks the device token first. |
| Which environment is **this device's token** in? | The same script with `--email <account>`: a silent `background` push to each registered device on both gateways. Only the production gateway accepting it means the backend can reach it. Devices are printed by position, never by token. Exit 0 only if every device is a production token. | A 200 is APNs' **acceptance**, not delivery. "Silent" is Apple's documented behaviour for a `content-available`-only push; it has not been observed on a device here. |
| Did the phone **receive** it? | The notification appearing on the device; record it in `MysteryMixClub-4vii.30`. | Nothing server-side can show this. |

On the Droplet the script needs the runtime environment systemd normally
injects (the APNs key and `DATABASE_URL`), loaded the same way the deploy loads
it:

```bash
sudo -u mysterymixclub bash -c '
  cd /home/mysterymixclub/app/backend &&
  set -a && source /etc/mysterymixclub/staging.env && set +a &&
  .venv/bin/python -m scripts.probe_apns_environment --check-credentials'
# for a device: replace --check-credentials with --email someone@example.com
```

Prod's file is `/etc/mysterymixclub/prod.env`; prod access is never ad hoc.

Two further separations the earlier docs blurred: **OS permission** is not
**registration** (an account with permission granted and both push preferences
on had no `device_push_tokens` row at all; `MysteryMixClub-4vii.32`), and a build's **API target** is
its own fact -- iOS builds default to `https://staging.mysterymixclub.com`
unless `VITE_IOS_API_BASE_URL` is set at build time (`vite.ios.config.ts`), so
a staging build registers on staging, never on prod.

**Evidence recorded 2026-09-20.** *Not available:* the archive or `.ipa` of
TestFlight build 1.0 (8) -- the local archives here are all build 1 or 2, so its
exported signing cannot be checked and no claim about it is made. *Established:*
staging's APNs key, Key ID and Team ID are accepted by both Apple gateways (a
fake token got `BadDeviceToken`, not `403`); staging's access log shows the
installed iPhone app (WebView user agent, cross-origin preflights) calling the
staging API, so its target is staging; and staging held **zero** device tokens
at that moment. That last fact is consistent with a device that never
registered and equally with one that registered and then logged out (logout
unregisters), so *which* happened is not established. `MysteryMixClub-4vii.32`
closes both gaps in the client, but it is merged, not yet observed on a device,
and it needs a new build to reach the phone. The definitive checks for that
build: `ios-check-push-entitlement.sh` on the exported `.ipa`, then the probe
with `--email` after it registers, then the notification appearing
(`MysteryMixClub-4vii.30`).

**Still needs device evidence**, blocked on the two manual Developer Portal
steps above: permission granted/denied/dismissed, a real push received in
foreground/background/terminated app states, tap-to-deep-link, each
preference toggle actually suppressing its channel, and logout clearing the
device's registration. Record outcomes on `MysteryMixClub-4vii.30`.

## What still needs device evidence

Physical-device runs must record, separately and honestly: native permission granted with no browser popup; denied and restricted permission; an account with no eligible subscription; an interrupted network mid-build; repeated taps; and a return to MMC after opening Apple Music. Record the outcomes on `MysteryMixClub-yyuq`. Never record tokens, private notes, or invitation URLs in diagnostics. A simulator can help with layout; it does not satisfy the PRD's physical-device acceptance gate.
