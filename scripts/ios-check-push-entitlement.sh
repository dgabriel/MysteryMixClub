#!/usr/bin/env bash
#
# MysteryMixClub -- which APNs environment is this iOS build signed for?
#
# Usage: scripts/ios-check-push-entitlement.sh <exported .ipa | .app | .xcarchive>
#
# Reads the aps-environment entitlement the build is ACTUALLY SIGNED with and the
# one its provisioning profile grants. That value is what decides whether the
# device mints a production or a sandbox push token, and the backend only talks
# to the production gateway (docs/adr/0033-apns-production-gateway-only.md).
#
# Point it at the thing that gets uploaded: the .ipa Xcode exports for
# TestFlight/App Store. A .xcarchive is signed for DEVELOPMENT (Apple
# Development identity) until it is exported; per Apple's documentation, export
# re-signs it with the distribution profile, which is what sets aps-environment
# for the uploaded build. That re-signing is standard behaviour, NOT something
# this script or the archives on this Mac can show, so for an archive the script
# says "inconclusive" rather than reporting its development value as an answer
# (MysteryMixClub-4vii.35).
#
# Exit status: 0 = production (fine for the backend), 1 = development, no push
# entitlement, or an unsigned bundle (this build cannot receive pushes from the
# backend), 2 = bad usage or unreadable input, 3 = a pre-export archive
# (inconclusive by nature).
#
# Prints no secret: only the signing authority, version and entitlement values.

set -euo pipefail

usage() {
  echo "Usage: scripts/ios-check-push-entitlement.sh <exported .ipa | .app | .xcarchive>" >&2
  exit 2
}

[ $# -eq 1 ] || usage
# Tab-completing a directory (.app / .xcarchive) leaves a trailing slash.
INPUT="${1%/}"
[ -e "$INPUT" ] || { echo "error: '$INPUT' does not exist." >&2; usage; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

KIND=""
APP=""
case "$INPUT" in
  *.ipa)
    KIND="ipa"
    if ! unzip -q "$INPUT" 'Payload/*' -d "$WORK" 2>/dev/null; then
      echo "error: '$INPUT' could not be read as an .ipa (not a zip, or no Payload/ inside)." >&2
      exit 2
    fi
    APP="$(ls -d "$WORK"/Payload/*.app 2>/dev/null | head -1 || true)"
    ;;
  *.xcarchive)
    KIND="archive"
    APP="$(ls -d "$INPUT"/Products/Applications/*.app 2>/dev/null | head -1 || true)"
    ;;
  *.app)
    KIND="app"
    APP="$INPUT"
    ;;
  *) usage ;;
esac
[ -n "$APP" ] && [ -d "$APP" ] || { echo "error: no .app found inside '$INPUT'." >&2; exit 2; }

# Empty (not an error line on stdout) when the file is missing/empty or the key is absent.
plist_value() {
  [ -s "$1" ] || return 0
  /usr/libexec/PlistBuddy -c "Print :$2" "$1" 2>/dev/null || true
}

BUNDLE_ID="$(plist_value "$APP/Info.plist" CFBundleIdentifier)"
VERSION="$(plist_value "$APP/Info.plist" CFBundleShortVersionString)"
BUILD="$(plist_value "$APP/Info.plist" CFBundleVersion)"
# `|| true` inside the group: an unsigned bundle makes codesign fail, and under
# pipefail that would end the script before it prints a verdict.
AUTHORITY="$({ codesign -dvv "$APP" 2>&1 || true; } | sed -n 's/^Authority=//p' | head -1)"

codesign -d --entitlements :- "$APP" 2>/dev/null >"$WORK/signed.plist" || true
SIGNED_APS="$(plist_value "$WORK/signed.plist" aps-environment)"
TASK_ALLOW="$(plist_value "$WORK/signed.plist" get-task-allow)"

PROFILE_APS=""
if [ -f "$APP/embedded.mobileprovision" ]; then
  security cms -D -i "$APP/embedded.mobileprovision" 2>/dev/null >"$WORK/profile.plist" || true
  PROFILE_APS="$(plist_value "$WORK/profile.plist" Entitlements:aps-environment)"
fi

echo "input:               $INPUT ($KIND)"
echo "bundle id:           ${BUNDLE_ID:-?}"
echo "version (build):     ${VERSION:-?} (${BUILD:-?})"
echo "signed by:           ${AUTHORITY:-<unsigned or unreadable>}"
echo "get-task-allow:      ${TASK_ALLOW:-<absent>}   (true = a development-style build)"
echo "aps-environment:     signed=${SIGNED_APS:-<absent>}  profile=${PROFILE_APS:-<absent>}"
echo

if [ "$KIND" = "archive" ]; then
  echo "INCONCLUSIVE: this is a pre-export archive. It is signed with a development identity"
  echo "until it is exported. Per Apple's documentation, export re-signs it with the"
  echo "distribution profile and that sets aps-environment for the uploaded build -- but that"
  echo "is documented behaviour, not something an archive can show. Run this on the exported"
  echo ".ipa, or probe a registered token (backend/scripts/probe_apns_environment.py)."
  exit 3
fi

if [ -z "$AUTHORITY" ]; then
  echo "NOT OK: this bundle is unsigned, or its signature could not be read, so there is no"
  echo "aps-environment to report. A build that reaches a device is always signed."
  exit 1
fi

case "$SIGNED_APS" in
  production)
    echo "OK: signed for the PRODUCTION APNs environment; tokens from this build work with the backend's gateway."
    exit 0
    ;;
  development)
    echo "NOT OK: signed for the DEVELOPMENT (sandbox) APNs environment. Tokens from this build are"
    echo "rejected by the production gateway the backend uses, so it cannot receive pushes."
    echo "Distribute a build exported for TestFlight/App Store instead (docs/adr/0033)."
    exit 1
    ;;
  *)
    echo "NOT OK: no aps-environment entitlement in the signature. The Push Notifications capability"
    echo "is missing from the App ID or its provisioning profile, so this build cannot register."
    exit 1
    ;;
esac
