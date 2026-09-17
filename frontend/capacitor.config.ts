import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.mysterymixclub.app',
  appName: 'Mystery Mix Club',
  webDir: 'dist-ios',
  // 'debug' was useful while diagnosing blank-WebView crashes during the
  // milestone-2 build-out; that's done now (the real app runs correctly end
  // to end, ADR 0032), so this reverts to 'none' -- a release build
  // shouldn't ship verbose WebView console logging (MysteryMixClub-4vii.18).
  loggingBehavior: 'none',
};

export default config;
