import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  // Prototype identifier; select the owner's team in Xcode before device signing.
  appId: 'com.mysterymixclub.iospoc',
  appName: 'MMC iOS Proof',
  webDir: 'dist-ios',
  loggingBehavior: 'none',
};

export default config;
