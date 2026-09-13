import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MusicProof } from './MusicProof';
import { music, nativeMusicAvailable } from './music';

vi.mock('./music', async importOriginal => {
  const original = await importOriginal<typeof import('./music')>();
  return { ...original, nativeMusicAvailable: vi.fn(), music: {
    status: vi.fn(), authorize: vi.fn(), inspect: vi.fn(),
    signIn: vi.fn(), sessionStatus: vi.fn(), signOut: vi.fn(),
    createPlaylist: vi.fn(), reconcile: vi.fn(), openMusic: vi.fn(),
  } };
});

const eligible = {
  authorization: 'authorized' as const, canPlayCatalogContent: true,
  hasCloudLibraryEnabled: true, tokenAvailable: true,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(nativeMusicAvailable).mockReturnValue(true);
  vi.mocked(music.status).mockResolvedValue({ authorization: 'notDetermined' });
  vi.mocked(music.sessionStatus).mockResolvedValue({ signedIn: false });
});

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Get the app to the state every playlist test starts from: a live MMC session
 *  and granted Apple Music permission. */
async function ready() {
  vi.mocked(music.signIn).mockResolvedValue({ signedIn: true, displayName: 'Dawn', email: 'd@example.com' });
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'authorized' });
  vi.mocked(music.inspect).mockResolvedValue(eligible);
  render(<MusicProof />);
  await screen.findByText('Not signed in.');
  type('Server address', 'http://192.168.1.20:8000');
  type('Email', 'd@example.com');
  type('Password', 'hunter2hunter2');
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  await screen.findByText('Signed in as Dawn.');
  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  await screen.findByText('Apple Music subscription is available.');
  type('Mix id', '3f1b0c9e-2d44-4a7b-9c31-6b0b2d5e8a10');
}

it('does not request native authorization while rendering or in a browser', async () => {
  vi.mocked(nativeMusicAvailable).mockReturnValue(false);
  render(<MusicProof />);
  expect(screen.getByRole('button', { name: 'Connect Apple Music' })).toBeDisabled();
  expect(music.authorize).not.toHaveBeenCalled();
  expect(music.status).not.toHaveBeenCalled();
  expect(music.sessionStatus).not.toHaveBeenCalled();
});

it('settles denied permission without attempting token retrieval', async () => {
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'denied' });
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  await screen.findByText('Permission denied');
  expect(music.inspect).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Connect Apple Music' })).toBeEnabled();
});

it('continues the check after authorization and blocks repeated taps', async () => {
  let resolveAuthorization!: (value: { authorization: 'authorized' }) => void;
  vi.mocked(music.authorize).mockReturnValue(new Promise(resolve => { resolveAuthorization = resolve; }));
  vi.mocked(music.inspect).mockResolvedValue(eligible);
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  fireEvent.click(screen.getByRole('button', { name: 'Checking Apple Music' }));
  expect(music.authorize).toHaveBeenCalledTimes(1);
  resolveAuthorization({ authorization: 'authorized' });
  await screen.findByText('Apple Music subscription is available.');
  expect(music.inspect).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Check connection' })).toBeEnabled();
});

it('discards old eligibility when returning after permission is revoked', async () => {
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'authorized' });
  vi.mocked(music.inspect).mockResolvedValue(eligible);
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  await screen.findByText('Apple Music subscription is available.');
  vi.mocked(music.status).mockResolvedValue({ authorization: 'denied' });
  fireEvent(document, new Event('visibilitychange'));
  await screen.findByText('Permission denied');
  expect(screen.queryByText('Apple Music subscription is available.')).not.toBeInTheDocument();
});

it('shows a recoverable timeout without echoing native error details', async () => {
  vi.mocked(music.authorize).mockRejectedValue({ code: 'TIMEOUT', message: 'private-token-sentinel' });
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('did not finish in time');
  expect(screen.queryByText(/private-token-sentinel/)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Connect Apple Music' })).toBeEnabled());
});

it('drops the password from component state once sign-in has spent it', async () => {
  await ready();
  expect(music.signIn).toHaveBeenCalledWith({
    apiBaseUrl: 'http://192.168.1.20:8000', email: 'd@example.com', password: 'hunter2hunter2',
  });
  // The field unmounts with the signed-out form; what matters is that it is not
  // still holding the secret when that form comes back.
  vi.mocked(music.signOut).mockResolvedValue({ signedIn: false });
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByText('Not signed in.');
  expect((screen.getByLabelText('Password') as HTMLInputElement).value).toBe('');
});

it('reports a failed sign-in as the server stated it, with no session', async () => {
  vi.mocked(music.signIn).mockRejectedValue({ code: 'INVALID_CREDENTIALS' });
  render(<MusicProof />);
  await screen.findByText('Not signed in.');
  type('Server address', 'http://192.168.1.20:8000');
  type('Email', 'd@example.com');
  type('Password', 'wrong-password');
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('did not match an account');
  expect(screen.getByText('Not signed in.')).toBeInTheDocument();
});

it('will not build a playlist without both a session and Apple permission', async () => {
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'authorized' });
  vi.mocked(music.inspect).mockResolvedValue(eligible);
  render(<MusicProof />);
  await screen.findByText('Not signed in.');
  type('Mix id', '3f1b0c9e-2d44-4a7b-9c31-6b0b2d5e8a10');
  expect(screen.getByRole('button', { name: 'Build playlist' })).toBeDisabled();
  expect(screen.getByText('Sign in above before building a playlist.')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Connect Apple Music' }));
  await screen.findByText('Apple Music subscription is available.');
  // Apple permission alone is still not enough.
  expect(screen.getByRole('button', { name: 'Build playlist' })).toBeDisabled();
  expect(music.createPlaylist).not.toHaveBeenCalled();
});

it('reports only the track count the server confirmed, and why tracks were skipped', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockResolvedValue({
    playlistName: 'Night Drives: mix 3', trackCount: 8, totalCount: 10,
    unmatched: [
      { title: 'Basement Take', artist: 'Ora', reason: 'source_only', source: 'bandcamp', sourceUrl: 'https://ora.bandcamp.com/track/basement-take' },
      { title: 'Held Note', artist: 'Vell', reason: 'no_catalog_match', source: '', sourceUrl: '' },
    ],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/8 of 10 tracks/);
  expect(screen.getByText(/skipped rather than guessed at/)).toBeInTheDocument();
  expect(screen.getByText(/does not carry this track in your storefront/)).toBeInTheDocument();
  expect(music.createPlaylist).toHaveBeenCalledWith(
    expect.objectContaining({ mixId: '3f1b0c9e-2d44-4a7b-9c31-6b0b2d5e8a10' }),
  );
});

it('treats a build that never answered as unknown and blocks a blind retry', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockRejectedValue({ code: 'TIMEOUT' });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/nobody knows whether it finished/);
  expect(screen.getByRole('button', { name: 'Build playlist' })).toBeDisabled();
  expect(screen.queryByText(/tracks/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Check this mix' })).toBeEnabled();
});

it('a known failure is retryable, unlike an unanswered one', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockRejectedValue({ code: 'APPLE_SERVICE_ERROR' });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was created');
  expect(screen.queryByText(/nobody knows whether it finished/)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Build playlist' })).toBeEnabled());
});

it('reconciles both sides and unblocks building once the answer is known', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockRejectedValue({ code: 'TIMEOUT' });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/nobody knows whether it finished/);

  vi.mocked(music.reconcile).mockResolvedValue({
    serverHasRecord: true, playlistName: 'Night Drives: mix 3', found: true, matchCount: 1, trackCount: 8,
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check this mix' }));
  await screen.findByText(/has it, with 8 tracks/);
  expect(screen.queryByText(/nobody knows whether it finished/)).not.toBeInTheDocument();
  // Building is a decision again, and it is now plainly a rebuild.
  expect(screen.getByRole('button', { name: 'Rebuild playlist' })).toBeEnabled();
});

it('separates what the server recorded from what reached this iPhone', async () => {
  await ready();
  vi.mocked(music.reconcile).mockResolvedValue({
    serverHasRecord: true, playlistName: 'Night Drives: mix 3', found: false, matchCount: 0,
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check this mix' }));
  await screen.findByText(/not in this iPhone’s library yet/);
  expect(screen.getByText(/has a playlist on record/)).toBeInTheDocument();
});

it('says it is safe to build when neither side has a playlist', async () => {
  await ready();
  vi.mocked(music.reconcile).mockResolvedValue({
    serverHasRecord: false, playlistName: '', found: false, matchCount: 0,
  });
  fireEvent.click(screen.getByRole('button', { name: 'Check this mix' }));
  await screen.findByText(/safe to build one/);
  expect(screen.queryByRole('button', { name: 'Open Apple Music' })).not.toBeInTheDocument();
});

it('does not claim the handoff reached the playlist', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockResolvedValue({
    playlistName: 'Night Drives: mix 3', trackCount: 10, totalCount: 10, unmatched: [],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/10 of 10 tracks/);

  vi.mocked(music.openMusic).mockResolvedValue({ opened: true });
  fireEvent.click(screen.getByRole('button', { name: 'Open Apple Music' }));
  await screen.findByText(/cannot tell whether you got there/);
  // No link is offered: a library playlist URL does not resolve on mobile.
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
});

it('says so when the device refuses to open Apple Music', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockResolvedValue({
    playlistName: 'Night Drives: mix 3', trackCount: 10, totalCount: 10, unmatched: [],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/10 of 10 tracks/);

  vi.mocked(music.openMusic).mockResolvedValue({ opened: false });
  fireEvent.click(screen.getByRole('button', { name: 'Open Apple Music' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('could not open Apple Music');
  expect(screen.queryByText(/cannot tell whether you got there/)).not.toBeInTheDocument();
});

it('clears mix state on sign-out so the next account starts clean', async () => {
  await ready();
  vi.mocked(music.createPlaylist).mockResolvedValue({
    playlistName: 'Night Drives: mix 3', trackCount: 10, totalCount: 10, unmatched: [],
  });
  fireEvent.click(screen.getByRole('button', { name: 'Build playlist' }));
  await screen.findByText(/10 of 10 tracks/);

  vi.mocked(music.signOut).mockResolvedValue({ signedIn: false });
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByText('Not signed in.');
  expect(screen.queryByText(/10 of 10 tracks/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Open Apple Music' })).not.toBeInTheDocument();
});
