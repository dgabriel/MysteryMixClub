# ADR 0033: Send to APNs' production gateway only; test push on distribution-signed builds

**Status:** Accepted
**Date:** 2026-09-20

## Context

Push notifications (IOS-04, `MysteryMixClub-4vii.25`) shipped with a hardcoded
production gateway (`api.push.apple.com`) and the reasoning "every build this
project ships, TestFlight included, is Release-signed, and a Release-signed
build always uses APNs' production environment." When a real TestFlight device
received nothing (`MysteryMixClub-4vii.35`), that reasoning was re-examined and
found to be wrong in its mechanism, even though it may be right in its outcome.

What decides a device token's environment is **the provisioning profile the app
is signed with**, not the Xcode build configuration. Apple's `aps-environment`
documentation says the entitlement's value comes from provisioning. A build
signed with a development profile mints a *sandbox* token; one signed with a
distribution profile mints a *production* token. Apple documents that a token
from the other environment is answered with `BadDeviceToken`, so a mismatch
is indistinguishable, on the wire, from a dead token.

Evidence gathered on 2026-09-20:

- `frontend/ios/App/App/App.entitlements` says `production`, yet every local
  `.xcarchive` on the maintainer's Mac is signed `Apple Development` with
  `get-task-allow` and `aps-environment=development` (signature and profile
  agree). The signed value follows the provisioning profile, not the checked-in
  file, so the file's value is not what ships.
- Those archives are pre-export, so they say nothing certain about the build
  uploaded to TestFlight. Apple documents that exporting for App Store Connect
  re-signs with the distribution profile; that was **not** observed here. The
  uploaded build 1.0 (8) has no archive on this machine (local archives are
  builds 1 and 2), so its signing could not be checked directly.
- Staging's APNs credentials are accepted: a token belonging to no device drew
  `BadDeviceToken` (not `403`) from both Apple gateways. (An APNs key can be
  restricted to one environment, so a sandbox `403` alone would not mean the
  backend's production path is broken.)
- APNs checks the device token before the topic (observed: a fake token with a
  bogus topic still drew `BadDeviceToken`; only an empty topic drew
  `MissingTopic` first), so `BadDeviceToken` says nothing about the topic.

## Decision

**The backend talks to the production gateway only, and push is tested on
builds signed for distribution (TestFlight, App Store).** An Xcode "Run" onto a
device is development-signed, mints sandbox tokens, and is **not supported for
push**. No sandbox toggle and no environment-aware routing is added.

This is chosen because:

- Every build that carries real users' notifications is a distribution build,
  and the project's device testing already goes through TestFlight.
- Environment-aware routing is not a small switch. It needs the build's
  environment reported at registration (read from the embedded provisioning
  profile in native code, since JavaScript cannot see it), a new column and
  migration, sandbox tokens isolated from production ones in every query and in
  retirement, and a second gateway path to test. That is real surface for a
  workflow nobody currently needs.
- Adding a toggle because a *pre-export archive* says `development` would fix a
  problem that has not been shown to exist for the uploaded build.

A sandbox token that reaches the backend is self-cleaning rather than harmful:
the production gateway answers `BadDeviceToken`, and once the process has had a
send accepted for the topic (`MysteryMixClub-4vii.33`) that registration is
retired. It receives nothing, and the device re-registers on its next launch.

Verification is made cheap and honest instead of assumed:

- `scripts/ios-check-push-entitlement.sh <exported .ipa>` reports the signed and
  profile `aps-environment` of the artifact that is uploaded, and refuses to
  answer for a pre-export archive.
- `backend/scripts/probe_apns_environment.py` asks both Apple gateways, with a
  silent `background` push, which environment a registered device's token is
  in, and separately whether Apple accepts the backend's credentials.

## Consequences

Push cannot be exercised from an Xcode debug run; that is documented, not
hidden. A first TestFlight build after this change should be checked with the
script before it is uploaded, and its registered token with the probe after.
If the build turns out to be development-signed, the fix is in how it is
exported, not in the backend.

## Revisit if

Push needs to work on development-signed builds (a team that debugs push
through Xcode runs, or a second environment that must not use production
tokens). Then add the environment to the registration, store it, and route and
retire per environment, as above. Do not do it merely because a `.xcarchive`
shows `development`.

## References

- [`aps-environment` entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/aps-environment)
- [Handling notification responses from APNs](https://developer.apple.com/documentation/usernotifications/handling-notification-responses-from-apns)
- [ADR 0032](0032-run-the-real-web-app-inside-the-capacitor-shell.md) — push
  registration was left native there
- `docs/ios/README.md` → "Which APNs environment is a build in?"
- `MysteryMixClub-4vii.32` (registration), `.33` (retirement), `.35` (this
  decision), `.30` (device evidence)
