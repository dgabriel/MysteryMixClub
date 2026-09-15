# ADR 0030: Carry the integration proof's architecture into milestone 2, with four items resolved first

**Status:** Accepted
**Date:** 2026-09-13

## Context

[ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md) set out to
prove, on a physical iPhone, that Capacitor plus a native Swift MusicKit bridge
could authorize, build a playlist through the *existing* server API, hand off to
Apple Music, and resume MMC context. [ADR 0029](0029-native-owns-the-http-boundary-in-the-ios-proof.md)
decided the native layer would make the MMC API calls directly rather than
bridge a credential into the WebView. Neither ADR approved anything past that —
0028 said so explicitly ("does not approve the full PRD scope or a production
deployment").

The proof (MysteryMixClub-yyuq) is now complete. On Dawn's own iPhone, against a
local dev backend:

- Native `MusicAuthorization` ran with no browser popup.
- `POST /mixes/{id}/apple-playlist` — unmodified — accepted a Music User Token
  obtained natively. This was the single open question ADR 0028 posed, and it
  is answered: **yes**.
- Handoff to Apple Music and resume back to MMC preserved session and mix
  state.
- Denied permission, a real interrupted network, and repeated taps all
  resolved into the states the plugin was designed to produce, not a hang or a
  silent failure. (Two apparent failures during testing turned out to be a
  message rendered off-screen — fixed in `MusicProof.tsx` — and a test
  methodology gap, not defects in the reject pipeline itself; see the bead's
  notes for the full trace through Capacitor's own bridge source.)

Two scenarios from the PRD's IOS-02 requirement — an ineligible Apple Music
subscription, and OS-level restricted access — were deliberately not
exercised. Both need setup this pass didn't have available (a second Apple ID
with no subscription; Screen Time content restrictions), and Dawn chose to
defer rather than build that setup now. The *positive* eligibility path
(`canPlayCatalogContent`, `hasCloudLibraryEnabled`) was exercised as part of
every successful build.

The PRD (§9) frames what comes next as milestone 2, "Usable iOS alpha": secure
MMC sessions, links, existing member screens, draft preservation, and initial
notification delivery. That is a materially larger surface than the four
endpoints this proof touched.

## Decision

**Carry the proof's architecture forward as the basis for milestone 2**:
Capacitor with a native Swift bridge, the existing server API untouched, and —
for now — the native layer making MMC's HTTP calls directly rather than the
WebView.

That carry-forward is qualified, not unconditional. Four things this proof
deliberately left open must be resolved as part of scoping milestone 2, not
discovered mid-build:

1. **Session strategy is unproven past a single access-token lifetime.** The
   native layer retains the refresh cookie in `URLSession`'s shared store, but
   nothing calls `/auth/refresh`. IOS-01 requires expiry recovery, account
   switching, and logout-all — none of which this proof attempted with a real
   member account. Design and prove the refresh path before any real account
   signs in through this app, not the disposable local test account this proof
   used.

2. **The native-owns-HTTP pattern was validated at four endpoints, not the
   member loop's true size.** IOS-05 alone (submissions, votes, notes,
   invites, club and mix management) is dozens of routes. Decide deliberately
   whether milestone 2 keeps writing native Swift per endpoint, adopts
   `CapacitorHttp` so the existing `frontend/src/services/api.ts` client can be
   reused with the WebView's fetches routed through native transport, or moves
   to an allowlisted WebView origin with a native-held refresh token. ADR
   0029's own "Revisit if" names the first two; this is that revisit, due at
   milestone 2 scoping rather than after code has already been written against
   an unexamined default.

3. **The playlist endpoint's ambiguous 401 needs a real fix.**
   MysteryMixClub-6x45 tracks it: `POST /mixes/{id}/apple-playlist` returns 401
   for both an expired MMC session and an expired Music User Token, currently
   told apart only by matching a hardcoded detail string. That was an
   acceptable interim for a proof with one caller; it is not acceptable once
   real sessions expire under real members.

4. **Minimum iOS version: settled at 16.0, permanently.** The PRD's own
   decision table (§10) lists "Supported devices and OS" as unresolved,
   deferred until after SDK validation. That validation has now happened —
   `MusicLibraryRequest`, the mechanism behind "Check this mix," requires
   iOS 16, and that reconciliation is load-bearing (IOS-03's duplicate-
   playlist prevention), not optional polish. **Decision: iOS 16.0 is the
   floor and MMC will not lower it to accommodate an older device.** Given
   16.0 shipped in 2022, this excludes only phones that were already old when
   it released.

   A device below the floor is not simply turned away silently. MMC already
   runs as a PWA in any mobile browser regardless of iOS version — the native
   app adds native Apple Music auth, push, and the reconciliation behavior
   above, but isn't the only way to use MMC. Milestone 2 must give an
   unsupported member MMC-authored guidance that says so, rather than relying
   on Apple's own generic "requires iOS 16" gating at the App Store/TestFlight
   listing: point them at continuing on the existing PWA in Safari, not just
   at an upgrade they may not be able to make. Where exactly that copy lives
   (invite email, invite landing page, a TestFlight-page note) is milestone-2
   scoping work, not decided here.

The two skipped scenarios are recorded as a deliberate scope decision, not a
silent gap: milestone 2 should decide whether ineligible-subscription and
restricted-access handling need their own device evidence before release, or
whether the code paths already written for them (`SUBSCRIPTION_REQUIRED`,
`restricted` in `MusicProof.tsx`) are close enough in kind to the exercised
paths to ship on code review alone.

## Consequences

Milestone 2 does not start from zero: the authorization flow, the error-code
vocabulary, the busy/timeout guard pattern, and the uncertain-outcome-blocks-
retry design in `MusicPlugin.swift` all extend rather than get rewritten.

It also does not start from "done." Items 1–3 above are prerequisites, not
parallel work — building member-facing screens against a session strategy that
silently drops after 60 minutes, or against a native HTTP pattern nobody has
decided will scale, produces exactly the kind of decision-by-accretion this
project's ADR process exists to prevent.

## Revisit if

Item 2's answer turns out to be `CapacitorHttp` or a WebView-origin change —
that is itself a decision this ADR defers, not one it makes.

## Addendum: items 1–4 resolved (2026-09-13, MysteryMixClub-mfhg)

**Item 1 (session refresh) — implemented.** `MMCAPIClient.send()` now catches a
`SESSION_EXPIRED` 401 on any authorized call, spends one `/auth/refresh`
attempt against the cookie already sitting in `URLSession.shared`'s cookie
storage, and retries the original call once on success. A failed refresh
(expired or `logout-all`-invalidated cookie) clears the session instead of
retrying again — there is no loop. Tracked and implemented under
MysteryMixClub-mfhg.1; account-switch and logout-all behavior still need
verification with a real member account (see the device test plan on that
issue), which is what "proven," not just "coded," requires here.

**Item 2 (does native-owns-HTTP scale) — decision: stay native for now.**
`MMCAPIClient` already generalized the request path (auth header, JSON
body/error handling, and now refresh-on-401) behind one `send()` helper, so
adding IOS-05's remaining routes is mostly one thin method per endpoint against
that helper, not bespoke plumbing each time — the dozens-of-routes concern this
ADR raised is smaller in practice than it looked before the refactor SwiftLint
forced (see ADR 0031). Switching to `CapacitorHttp` or a WebView-origin pattern
is a real migration with its own risk (losing the "credential never crosses the
bridge" property ADR 0029 chose), and nothing observed yet justifies paying
that cost pre-emptively. Concrete revisit trigger, not a vibe: if building out
IOS-05 shows each new endpoint costing meaningfully more than writing the
equivalent `frontend/src/services/api.ts` function did, or the plugin file
needs another SwiftLint-forced split within one milestone, treat that as the
signal to revisit rather than pushing further on the native path by default.

**Item 3 (ambiguous 401) — fixed.** `POST /mixes/{id}/apple-playlist`'s 401 now
carries a structured body (`{"detail": {"message": ..., "code":
"apple_auth_expired"}}`) instead of the plain-string shape every other 401 in
the app still uses; `get_current_user`'s own neutral 401 is deliberately left
untouched (TD §5's "one uniform detail" reasoning still applies there — this
was never about making every 401 structured, only the one endpoint where two
different failures were wire-indistinguishable). `MMCAPIClient` discriminates
on the `code` field, not the message text. MysteryMixClub-6x45's acceptance
criteria are met.

**Item 4 (iOS 16 floor) — decision stands; copy placement deferred.** iOS 16.0
remains the permanent floor (unchanged from the decision recorded above). The
unsupported-device guidance copy itself is **not** written yet: there is no
invite email, invite landing page, or TestFlight listing for this app today —
the iOS build has no distribution surface to put that copy on. Writing it now
would be copy with nowhere to live. Revisit when milestone 2 gives the iOS
build its first real distribution channel (TestFlight, most likely), and place
the PWA-fallback guidance there at that point.

## References

- [ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md)
- [ADR 0029](0029-native-owns-the-http-boundary-in-the-ios-proof.md)
- [iOS PRD](../ios/PRD-v0.1.md) — §9 milestones, §10 open decisions
- MysteryMixClub-yyuq — device evidence in full
- MysteryMixClub-6x45 — the ambiguous 401
