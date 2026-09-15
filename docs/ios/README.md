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
npm run ios:sync     # build the proof's web bundle and copy it into the iOS app
npm run ios:open     # open the project in Xcode
```

In Xcode, pick your iPhone as the run destination and press Run. The first run on a new device needs the device registered to the team, which selecting it as the destination does automatically.

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

## What still needs device evidence

Physical-device runs must record, separately and honestly: native permission granted with no browser popup; denied and restricted permission; an account with no eligible subscription; an interrupted network mid-build; repeated taps; and a return to MMC after opening Apple Music. Record the outcomes on `MysteryMixClub-yyuq`. Never record tokens, private notes, or invitation URLs in diagnostics. A simulator can help with layout; it does not satisfy the PRD's physical-device acceptance gate.
