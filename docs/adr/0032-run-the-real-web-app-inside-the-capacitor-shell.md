# ADR 0032: Run the real web app inside the Capacitor shell for milestone 2

**Status:** Accepted
**Date:** 2026-09-13

## Context

ADR 0030 named milestone 2's four prerequisites and, in its addendum, decided
item 2 ("does native-owns-HTTP scale past four endpoints") by choosing "stay
native for now" — grow `MMCAPIClient` with one Swift method per endpoint, the
same pattern the proof used. That framing implicitly assumed milestone 2's
UI would also be native: if every endpoint needs a hand-written Swift method,
something has to be calling those methods, and the proof's own
`MusicProof.tsx` + `ProofViewController` harness is not that something at any
real scale.

Dawn's instruction (2026-09-13): build out the full iOS member app now, as
completely as practical in this pass, stopping only at platform-admin
functionality, which the PRD (IOS-05) already scopes to web only. IOS-05
alone covers submissions, voting budgets, notes, reveals, club creation,
invitations, and organizer lifecycle controls — reimplementing that surface
natively, screen by screen, on top of a native HTTP client grown endpoint by
endpoint, is a multi-week rewrite of code that already exists, is tested, and
already runs correctly on a phone today (as a mobile-Safari PWA).

## Decision

**Run the existing `frontend/src` web app inside the Capacitor WebView as
the iOS app's primary UI**, exactly as it already runs in mobile Safari.
Point the iOS build (`vite.ios.config.ts` / `capacitor.config.json`) at the
real app instead of the standalone `frontend/ios-web` proof harness. The
WebView owns its own MMC session (access token in JS memory, refresh cookie)
via the existing `frontend/src/services/api.ts` — identical to today's web
behavior, not a new credential-exposure surface, since that token already
lives in JS on every platform this app runs on.

**Narrow what stays native to what genuinely cannot run in a WebView:**
Apple Music authorization and playlist creation (native MusicKit has no web
equivalent on iOS the way it does via MusicKit JS in a real browser — this is
the entire reason ADR 0028 exists) and, later, push notification
registration (APNs has no WebView equivalent). Everything else — submissions,
voting, notes, reveals, club/mix/invite management, results — runs as the
same React code already serving web members, making the same calls through
the same `services/api.ts` it always has.

**Apple Music integration moves into the real app, not a separate screen.**
`AppleMusicPlaylist.tsx` (the existing web component) gains a
`Capacitor.isNativePlatform()` branch: on iOS, it calls the native
`MMCMusicPlugin` instead of MusicKit JS. ADR 0029's specific, still-valid
concern — Apple's Music User Token must never reach the WebView's JS
context — is preserved: the actual `POST /mixes/{id}/apple-playlist` call
stays inside `MMCAPIClient` (Swift), not JS. What changes is that
`MMCAPIClient` no longer maintains its own independent sign-in; the real
app's already-authenticated access token is passed into the plugin call at
invocation time (one direction, JS → native, for a request the JS side
already holds full authority to make itself). This is not a new exposure —
the token is already resident in the calling JS context by construction, in
every deployment of this app.

**The standalone proof harness (`frontend/ios-web`, `MusicProof.tsx`,
`ProofViewController`) is retired**, not deleted outright yet — it proved
what ADR 0028 needed proven and its job is done; the real app's
`AppleMusicPlaylist.tsx` is now the actual integration surface.

**Platform admin is excluded at build time, not just role-gated.** `/admin`
and `/admin/metrics` already self-guard non-admins on web (redirect to
`/home`), but that still means the routes are *reachable* from an
admin-signed-in session. iOS never ships that surface at all — excluded from
the router when building for Capacitor, matching the PRD's explicit "web
only" scope for platform-admin operations.

## Consequences

Milestone 2's IOS-05 surface (and most of IOS-01) becomes close to free:
the same component tree, the same tests, the same design system compliance
already shipped for web now also serves iOS with no native rewrite. The
real remaining native work is: (1) the Apple Music bridge rework described
above, (2) push notifications (IOS-04), which still needs its own Apple
Developer Portal setup (APNs key/certificate) analogous to what MusicKit
required, and (3) anything genuinely iOS-specific in IOS-06 (background/
draft-preservation behavior a WebView doesn't get automatically).

This narrows, not reverses, ADR 0029: the Apple Music credential-boundary
decision stands exactly as written. What's withdrawn is only the
*generalization* of "native owns HTTP" from the proof to the entire member
app — that generalization is what this ADR declines.

## Revisit if

The WebView's session/cookie behavior on iOS turns out to have real gaps
against IOS-01's requirements (e.g., background/foreground session
recovery, deep-link handling into the WebView) that the existing web app's
assumptions don't already cover for a wrapped, non-browser-chrome context.

## References

- [ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md)
- [ADR 0029](0029-native-owns-the-http-boundary-in-the-ios-proof.md) — the
  Apple Music credential-boundary decision, unchanged by this ADR
- [ADR 0030](0030-carry-the-ios-proof-architecture-into-milestone-2.md) —
  item 2's "stay native for now" is narrowed by this ADR to the Apple Music
  boundary specifically, not the whole member app
- [iOS PRD](../ios/PRD-v0.1.md) — IOS-05's "exceptional platform-admin
  operations remain on web"
- MysteryMixClub-4vii — the milestone-2 build-out this ADR unblocks
