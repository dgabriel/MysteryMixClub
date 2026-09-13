# ADR 0028: Evaluate Capacitor and native MusicKit in an iPhone integration proof

**Status:** Proposed
**Date:** 2026-09-12

## Context

The [iOS PRD](../ios/PRD-v0.1.md) proposes reusing MMC's React interface and FastAPI backend while replacing browser Apple Music authorization with native authorization. The first milestone must prove the integration on a physical iPhone before committing to a release architecture. Work is tracked in MysteryMixClub-yyuq.

## Decision

Evaluate Capacitor with a small local Swift MusicKit bridge. Keep the existing web MusicKit path. Start with authorization, one mix playlist, external Apple Music handoff, and restoration of mix context. Push notifications and the complete iOS member loop follow the proof.

The existing server playlist endpoint accepts a per-request Music User Token and uses the authenticated MMC member to authorize mix access. Verify whether the native token provider can supply a compatible token before retaining that API boundary. Native authorization alone does not prove server playlist compatibility. If it cannot, separately design native playlist creation using server-resolved tracks without exposing hidden submission data.

MMC authentication is a separate integration gate. Do not assume Safari cookies transfer to the app, put session tokens in navigation URLs, or persist credentials in JavaScript storage. Record and validate the session transport, expiry, logout, and account-switch behavior before connecting the full interface to a real member account. MusicKit private signing keys remain server-side.

## Consequences

React reuse avoids an immediate interface rewrite, but introduces a native bridge and an Xcode build toolchain. Real-device evidence is required for permission, subscription eligibility, token compatibility, and playlist handoff. No native build or successful device test has yet been performed. This proposal does not approve the full PRD scope or a production deployment.

## Revisit if

Native authorization cannot support a secure playlist boundary, app session handling proves unsuitable, or the embedded React experience fails the PRD's accessibility and resume requirements. Consider React Native after identifying a concrete limitation.

## References

- https://capacitorjs.com/docs/getting-started/environment-setup
- https://developer.apple.com/musickit/
- https://developer.apple.com/documentation/musickit/musicdatarequest/tokenprovider
