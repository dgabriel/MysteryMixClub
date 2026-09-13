import { Capacitor, registerPlugin } from '@capacitor/core';

export type Authorization = 'notDetermined' | 'authorized' | 'denied' | 'restricted' | 'unknown';
export type MusicStatus = { authorization: Authorization };
export type MusicInspection = MusicStatus & {
  canPlayCatalogContent: boolean;
  hasCloudLibraryEnabled: boolean;
  tokenAvailable: boolean;
};

/** The MMC session, as the native layer reports it. There is no token here by
 *  design: the access token and the Music User Token both stay in Swift and
 *  never cross the bridge (ADR 0029). */
export type Session = { signedIn: boolean; displayName?: string; email?: string };

/** A track the server could not put on the playlist. `source`/`sourceUrl` are
 *  empty strings rather than null, since the bridge carries no null. */
export type UnmatchedTrack = {
  title: string;
  artist: string;
  reason: 'source_only' | 'no_catalog_match';
  source: string;
  sourceUrl: string;
};

/** Only what the server confirmed. Deliberately carries no playlist URL: a
 *  library playlist link does not resolve on a mobile client, so there is no
 *  honest link to offer (MysteryMixClub-ap25). */
export type PlaylistResult = {
  playlistName: string;
  trackCount: number;
  totalCount: number;
  unmatched: UnmatchedTrack[];
};

/** Both sides of "does this mix already have a playlist?". `serverHasRecord`
 *  is what MMC recorded; `found` is what this iPhone's own library holds, which
 *  is the only proof the playlist actually arrived here. `trackCount` is present
 *  only when `found`. */
export type Reconciliation = {
  serverHasRecord: boolean;
  playlistName: string;
  found: boolean;
  matchCount: number;
  trackCount?: number;
};

export type Handoff = { opened: boolean };

interface NativeMusicPlugin {
  status(): Promise<MusicStatus>;
  authorize(): Promise<MusicStatus>;
  inspect(): Promise<MusicInspection>;
  signIn(options: { apiBaseUrl: string; email: string; password: string }): Promise<Session>;
  sessionStatus(): Promise<Session>;
  signOut(): Promise<Session>;
  createPlaylist(options: { mixId: string; tzOffsetMinutes: number }): Promise<PlaylistResult>;
  reconcile(options: { mixId: string }): Promise<Reconciliation>;
  openMusic(): Promise<Handoff>;
}

export const nativeMusicAvailable = () =>
  Capacitor.getPlatform() === 'ios' && Capacitor.isPluginAvailable('MMCMusic');

export const music = registerPlugin<NativeMusicPlugin>('MMCMusic');

function errorCode(error: unknown): string {
  return typeof error === 'object' && error !== null && 'code' in error
    ? String((error as { code: unknown }).code)
    : '';
}

/**
 * Whether a failed playlist creation leaves an UNKNOWN result rather than a
 * known failure.
 *
 * The distinction drives real behavior: a request that never answered may still
 * have written the playlist, so the next step is to reconcile against the
 * library, not to press the button again. Everything else failed outright and is
 * safe to retry.
 */
export function isUncertainOutcome(error: unknown): boolean {
  const code = errorCode(error);
  return code === 'TIMEOUT' || code === 'NETWORK_ERROR';
}

export function musicErrorMessage(error: unknown): string {
  switch (errorCode(error)) {
    // Apple Music
    case 'PERMISSION_REQUIRED': return 'Allow Apple Music access before checking your connection.';
    case 'ACCOUNT_REQUIRED': return 'Sign in to Apple Music on this iPhone, then try again.';
    case 'PRIVACY_REQUIRED': return 'Open Apple Music and finish its account setup, then try again.';
    case 'TOKEN_REVOKED': return 'Apple Music access changed. Check permission and reconnect.';
    case 'TOKEN_UNAVAILABLE': return 'Apple Music did not return an authorization token. Check permission and try again.';
    case 'SUBSCRIPTION_REQUIRED': return 'An eligible Apple Music subscription is needed to build a playlist.';
    case 'APPLE_AUTH_EXPIRED': return 'Apple Music access expired. Connect Apple Music again, then rebuild.';
    case 'CONFIGURATION_REQUIRED': return 'MusicKit configuration needs attention in Xcode before this device test can continue.';
    case 'APPLE_NOT_CONFIGURED': return 'This server has no Apple Music configuration, so it cannot build a playlist.';
    case 'APPLE_SERVICE_ERROR': return 'Apple Music refused the request. Nothing was created. Try again shortly.';
    // MMC session
    case 'INVALID_CREDENTIALS': return 'That email and password did not match an account.';
    case 'SESSION_EXPIRED': return 'Your Mystery Mix Club session expired. Sign in again.';
    case 'NOT_SIGNED_IN': return 'Sign in to Mystery Mix Club before building a playlist.';
    case 'CREDENTIALS_REQUIRED': return 'Enter your email and password.';
    case 'SERVER_ADDRESS_INVALID': return 'That server address is not usable. Give a full http or https address.';
    // Request
    case 'MIX_ID_INVALID': return 'That mix id is not a valid identifier. Copy it from the mix page.';
    case 'MIX_NOT_FOUND': return 'No mix with that id. Check the id and try again.';
    case 'NOT_A_MEMBER': return 'This account is not a member of that club.';
    case 'REQUEST_REJECTED': return 'The server rejected the request. Check the mix id.';
    case 'RATE_LIMITED': return 'Too many attempts. Wait a few minutes, then try again.';
    // Transport and plumbing
    case 'NETWORK_ERROR': return 'Could not reach the server. Check the address and your connection.';
    case 'TIMEOUT': return 'The request did not finish in time. Check your connection and try again shortly.';
    case 'BUSY': return 'The previous check is still finishing. Try again shortly.';
    case 'SERVER_ERROR': return 'The server could not complete the request. Try again shortly.';
    default: return 'Something went wrong. Check your connection and try again.';
  }
}
