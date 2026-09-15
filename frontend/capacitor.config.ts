import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.mysterymixclub.app',
  appName: 'Mystery Mix Club',
  webDir: 'dist-ios',
  // 'none' hid the real app's console entirely while it was still just the
  // MusicKit proof; now that Capacitor runs the whole member app (ADR 0032),
  // a blank WebView crash has nowhere else to report to -- keep this on
  // during the milestone-2 build-out.
  loggingBehavior: 'debug',
};

export default config;
