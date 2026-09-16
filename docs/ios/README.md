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

## What still needs device evidence

Physical-device runs must record, separately and honestly: native permission granted with no browser popup; denied and restricted permission; an account with no eligible subscription; an interrupted network mid-build; repeated taps; and a return to MMC after opening Apple Music. Record the outcomes on `MysteryMixClub-yyuq`. Never record tokens, private notes, or invitation URLs in diagnostics. A simulator can help with layout; it does not satisfy the PRD's physical-device acceptance gate.
