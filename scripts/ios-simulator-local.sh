#!/usr/bin/env bash
# Build a local-only Debug simulator app without changing distribution settings.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SIMULATOR_ID="${1:?Usage: bash scripts/ios-simulator-local.sh <simulator-uuid> [http://localhost:8000]}"
API_ORIGIN="${2:-http://localhost:8000}"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/mmc-local-simulator.XXXXXX")"

# Keep the ATS exception in a generated plist, never in the shipping Info.plist.
python3 - "$REPO_ROOT/frontend/ios/App/App/Info.plist" "$BUILD_ROOT/Info.plist" <<'PY'
import plistlib
import sys
from pathlib import Path

source, destination = map(Path, sys.argv[1:])
plist = plistlib.loads(source.read_bytes())
plist["NSAppTransportSecurity"] = {"NSAllowsLocalNetworking": True}
plist["CFBundleDisplayName"] = "MMC Local Review"
destination.write_bytes(plistlib.dumps(plist))
PY

MMC_IOS_LOCAL_SIMULATOR=1 VITE_IOS_API_BASE_URL="$API_ORIGIN" \
  xcodebuild -project "$REPO_ROOT/frontend/ios/App/App.xcodeproj" \
  -scheme App -configuration Debug -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=$SIMULATOR_ID" \
  -derivedDataPath "$BUILD_ROOT/DerivedData" \
  INFOPLIST_FILE="$BUILD_ROOT/Info.plist" CODE_SIGNING_ALLOWED=NO build

APP_PATH="$BUILD_ROOT/DerivedData/Build/Products/Debug-iphonesimulator/App.app"
echo "Built local simulator app: $APP_PATH"
echo "API origin: $API_ORIGIN"
echo "Install with: xcrun simctl install $SIMULATOR_ID $APP_PATH"
