# Getting started with the iOS proof

The [PRD](PRD-v0.1.md) is the supplied draft, preserved unchanged. [ADR 0028](../adr/0028-prototype-ios-with-capacitor-and-native-musickit.md) records the proposed prototype architecture. Durable progress lives in Bead `MysteryMixClub-yyuq`.

## The tools in plain language

React continues to draw MMC's screens. Capacitor packages those screens in an iPhone application and lets JavaScript call native code. Swift is the language for the small Apple Music integration. Xcode builds, signs, and runs that application. Signing associates a build with your Apple development team and permitted devices. TestFlight is a later beta-distribution step.

## This Mac's readiness on September 12, 2026

macOS is 26.6.1 and Node is v26.7.0. The active developer directory is `/Library/Developer/CommandLineTools`; Xcode is absent from `/Applications`. No iOS project is present in the repository yet. Apple Developer Program enrollment and a physical iPhone with Apple Music access still need confirmation.

Capacitor 8's documented prerequisites are Node 22 or newer and Xcode 26 or newer. Prefer Swift Package Manager, the default for new Capacitor 8 iOS projects. See the [official setup guide](https://capacitorjs.com/docs/getting-started/environment-setup).

## First owner setup step

Install [Xcode from the Mac App Store](https://apps.apple.com/app/xcode/id497799835), launch it, and finish its first-run setup including iOS platform support. Apple account sign-in, license acceptance, and any device trust prompts require the owner's interaction. After installation, verify that `xcodebuild -version` reports full Xcode and that `xcode-select -p` points inside Xcode. If the command-line directory is still selected, configure Xcode's Command Line Tools selection in its settings.

The first physical-device run will also need the correct development team, an app identifier with the required MusicKit configuration, and an iPhone available for testing. Do not paste signing keys or account credentials into chat.

## What the first proof must establish

Use a test club and an explicit user action to create one playlist. Confirm native permission works without a browser popup, then validate its token against the existing server playlist boundary. Show only confirmed creation results. Open Apple Music if a usable playlist destination is available and restore the same MMC mix when returning.

Exercise denied permission, unavailable subscription, interrupted network, repeated taps, and app resume. A timeout after playlist creation is an uncertain outcome: reconcile before retrying. Existing server playlist support is not evidence that every retry is safe.

Device observations must distinguish authorization, MMC session, playlist creation, and handoff failures. Never record tokens, private notes, or invitation URLs in diagnostics. A simulator can help with layout; it does not satisfy the PRD's physical-device acceptance gate.

Implementation and native validation remain outstanding. The initial repository change contains documentation only, so application tests are not applicable.
