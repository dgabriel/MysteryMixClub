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
  plugins: {
    PushNotifications: {
      // How a push is shown while the app is OPEN (MysteryMixClub-4vii.34).
      // With no value here the native handler returns no presentation options,
      // so iOS drops a foreground push on the floor: the JS event fires but
      // nothing is displayed. `banner` + `list` is the standard system banner
      // that also lands in Notification Center; `alert` is deprecated on iOS.
      // No `sound` (the person is already looking at the app; quiet by
      // design) and no `badge` (the backend never sends a badge count).
      // Backgrounded and terminated delivery are unaffected: the system shows
      // those itself, and a tap still routes through the same
      // 'pushNotificationActionPerformed' listener. Nothing renders its own
      // in-app copy of the notification, so it is not shown twice.
      presentationOptions: ['banner', 'list'],
    },
  },
};

export default config;
