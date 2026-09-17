# ADR 0029: The native layer owns the HTTP boundary in the iOS proof

**Status:** Accepted — confirmed by physical-device evidence 2026-09-13, see [ADR 0030](0030-carry-the-ios-proof-architecture-into-milestone-2.md)
**Date:** 2026-09-13

## Context

[ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md) committed the
iOS proof to Capacitor plus a small Swift MusicKit bridge, and left two questions
open for the prototype to answer: whether a natively-obtained Music User Token
works against the existing server playlist API, and what the app's MMC session
transport should be. Work is tracked in MysteryMixClub-yyuq.

`POST /mixes/{id}/apple-playlist` takes a Music User Token per request and never
stores it (`backend/app/api/routes/apple_music.py`). The obvious way to reach it
from Capacitor is the one the web app already uses: get the token, hand it to
JavaScript, and call the existing `createApplePlaylist()` in
`frontend/src/services/api.ts`. That is maximum reuse and zero new networking
code.

It also puts an Apple credential inside a WKWebView, which is the one thing
`MusicPlugin.swift` was written to avoid ("Never return tokens through the
WebView bridge or log them"), and ADR 0028 names as a constraint. Two further
facts, found while scoping this work, make the reuse path worse than it looks:

- **The refresh cookie does not survive the move.** MMC's session is an in-memory
  access token plus an HttpOnly `SameSite=Lax` refresh cookie. A Capacitor
  WebView is origin `capacitor://localhost`, so every API call is cross-site and
  the refresh cookie is withheld. Reusing the web client verbatim yields a
  session that dies silently after 60 minutes with no refresh path. ADR 0028
  anticipated this ("Do not assume Safari cookies transfer to the app").
- **CORS becomes a deployment concern.** A WebView-origin fetch needs
  `capacitor://localhost` added to `ALLOWED_ORIGINS` on every environment the app
  ever talks to, including production.

## Decision

**Swift makes the MMC API calls; JavaScript never holds a credential.**

The `MMCMusic` plugin gains `signIn` / `sessionStatus` / `signOut` /
`createPlaylist`. It keeps the API base URL, the MMC access token, and the Music
User Token in native memory and returns only outcomes across the bridge:
whether a session exists, the signed-in display name, and the playlist result the
server confirmed. Neither the Apple token nor the MMC access token is ever a
bridge value.

**Keep the existing server API boundary unchanged.** The proof calls
`POST /auth/login`, `GET /users/me`, `POST /auth/logout` and
`POST /mixes/{id}/apple-playlist` exactly as the web client does. Answering ADR
0028's compatibility question means testing the deployed contract, not a new one.

**Confirm creation against the device library, not the response.** The plugin
adds `findLibraryPlaylist`, which reads the playlist back out of the local
library through `MusicLibraryRequest<Playlist>`. This is the reconciliation step
the PRD asks for after an uncertain result, and it is capability the web client
never had.

**Handoff opens Apple Music and says only what it knows.** `openMusic` reports
whether iOS accepted the URL. That is not evidence the playlist resolved, and the
UI does not describe it as such.

## Consequences

The Apple token's blast radius stops at the Swift layer, and the busy/timeout
guard already in `MusicPlugin.swift` now covers server calls too, so a repeated
tap cannot start overlapping playlist writes. CORS stops being an iOS concern
entirely: `URLSession` is not subject to it. Because the native session owns
`HTTPCookieStorage`, the refresh cookie is retained and a real refresh path stays
open to build later; the proof itself does not yet exercise refresh, so the
session is still access-token-lifetime only.

The cost is a second API client. Swift now duplicates a small amount of what
`api.ts` does, and the two can drift. That is bounded to four endpoints for as
long as this is a proof; a release architecture needs an explicit answer for how
the full member loop reaches the API, and this ADR does not supply one.

One gap surfaced and is deliberately not fixed here: the playlist endpoint
returns 401 both for an expired MMC session and for an expired Music User Token,
and the only discriminator is the response detail string. The plugin matches the
narrow, documented `"not authenticated"` constant and treats every other 401 as
Apple reauthorization, so an unknown 401 fails toward a reconnect rather than a
spurious logout. Filed as MysteryMixClub-6x45.

Dev builds reach a LAN backend over plain HTTP, so `Info.plist` gains
`NSAllowsLocalNetworking` and a local-network usage string. That relief is scoped
to local addresses and does not weaken ATS for the public internet; a build
pointed at staging or production needs neither.

**2026-09-13 update:** confirmed on a physical iPhone against a LAN dev backend
— sign-in, playlist creation via the unmodified server endpoint, reconciliation
against both the server record and the device's own library, and a real network
interruption all behave as designed. See
[ADR 0030](0030-carry-the-ios-proof-architecture-into-milestone-2.md) for
whether this four-endpoint pattern is the right shape once the full member loop
is in scope, rather than just this proof's slice of it.

## Revisit if

The proof shows the native token is not accepted by the existing playlist
endpoint, in which case the boundary itself is what changes, not its caller. Also
revisit when the full member loop lands: a React app talking to the API through a
native shim for every endpoint is a different proposition from four, and the
alternatives then are `CapacitorHttp` (native transport, `fetch` API) or an
allowlisted WebView origin with a native-held refresh token.

## References

- [ADR 0028](0028-prototype-ios-with-capacitor-and-native-musickit.md)
- [iOS PRD](../ios/PRD-v0.1.md) — IOS-01 (session), IOS-02 (connection), IOS-03 (playlist and handoff)
- https://developer.apple.com/documentation/musickit/musicdatarequest/tokenprovider
- https://developer.apple.com/documentation/musickit/musiclibraryrequest
- https://developer.apple.com/documentation/bundleresources/information_property_list/nsapptransportsecurity/nsallowslocalnetworking
