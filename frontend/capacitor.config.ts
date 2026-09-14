import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  // Prototype identifier; select the owner's team in Xcode before device signing.
  appId: 'com.mysterymixclub.iospoc',
  appName: 'MMC iOS Proof',
  webDir: 'dist-ios',
  // 'none' hid the real app's console entirely while it was still just the
  // MusicKit proof; now that Capacitor runs the whole member app (ADR 0032),
  // a blank WebView crash has nowhere else to report to -- keep this on
  // during the milestone-2 build-out.
  loggingBehavior: 'debug',
};

export default config;
