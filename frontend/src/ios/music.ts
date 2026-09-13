import { Capacitor, registerPlugin } from '@capacitor/core';

export type Authorization = 'notDetermined' | 'authorized' | 'denied' | 'restricted' | 'unknown';
export type MusicStatus = { authorization: Authorization };
export type MusicInspection = MusicStatus & {
  canPlayCatalogContent: boolean;
  hasCloudLibraryEnabled: boolean;
  tokenAvailable: boolean;
};

interface NativeMusicPlugin {
  status(): Promise<MusicStatus>;
  authorize(): Promise<MusicStatus>;
  inspect(): Promise<MusicInspection>;
}

export const nativeMusicAvailable = () =>
  Capacitor.getPlatform() === 'ios' && Capacitor.isPluginAvailable('MMCMusic');

export const music = registerPlugin<NativeMusicPlugin>('MMCMusic');

export function musicErrorMessage(error: unknown): string {
  const code = typeof error === 'object' && error !== null && 'code' in error ? error.code : '';
  switch (code) {
    case 'PERMISSION_REQUIRED': return 'Allow Apple Music access before checking your connection.';
    case 'ACCOUNT_REQUIRED': return 'Sign in to Apple Music on this iPhone, then try again.';
    case 'PRIVACY_REQUIRED': return 'Open Apple Music and finish its account setup, then try again.';
    case 'TOKEN_REVOKED': return 'Apple Music access changed. Check permission and reconnect.';
    case 'CONFIGURATION_REQUIRED': return 'MusicKit configuration needs attention in Xcode before this device test can continue.';
    case 'TIMEOUT': return 'Apple Music did not respond in time. Check your connection and try again shortly.';
    case 'BUSY': return 'The previous Apple Music check is still finishing. Try again shortly.';
    default: return 'Apple Music could not be checked. Check your connection and try again.';
  }
}
