import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MusicProof } from './MusicProof';
import { music, nativeMusicAvailable } from './music';

vi.mock('./music', async importOriginal => {
  const original = await importOriginal<typeof import('./music')>();
  return { ...original, nativeMusicAvailable: vi.fn(), music: {
    status: vi.fn(), authorize: vi.fn(), inspect: vi.fn(),
  } };
});

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(nativeMusicAvailable).mockReturnValue(true);
  vi.mocked(music.status).mockResolvedValue({ authorization: 'notDetermined' });
});

it('does not request native authorization while rendering or in a browser', async () => {
  vi.mocked(nativeMusicAvailable).mockReturnValue(false);
  render(<MusicProof />);
  expect(screen.getByRole('button', { name: 'Connect Apple Music' })).toBeDisabled();
  expect(music.authorize).not.toHaveBeenCalled();
  expect(music.status).not.toHaveBeenCalled();
});

it('settles denied permission without attempting token retrieval', async () => {
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'denied' });
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button'));
  await screen.findByText('Permission denied');
  expect(music.inspect).not.toHaveBeenCalled();
  expect(screen.getByRole('button')).toBeEnabled();
});

it('continues the check after authorization and blocks repeated taps', async () => {
  let resolveAuthorization!: (value: { authorization: 'authorized' }) => void;
  vi.mocked(music.authorize).mockReturnValue(new Promise(resolve => { resolveAuthorization = resolve; }));
  vi.mocked(music.inspect).mockResolvedValue({ authorization: 'authorized', canPlayCatalogContent: true,
    hasCloudLibraryEnabled: true, tokenAvailable: true });
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button'));
  fireEvent.click(screen.getByRole('button'));
  expect(music.authorize).toHaveBeenCalledTimes(1);
  resolveAuthorization({ authorization: 'authorized' });
  await screen.findByText('Apple Music subscription is available.');
  expect(music.inspect).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('button', { name: 'Check connection' })).toBeEnabled();
});

it('discards old eligibility when returning after permission is revoked', async () => {
  vi.mocked(music.authorize).mockResolvedValue({ authorization: 'authorized' });
  vi.mocked(music.inspect).mockResolvedValue({ authorization: 'authorized', canPlayCatalogContent: true,
    hasCloudLibraryEnabled: true, tokenAvailable: true });
  render(<MusicProof />);
  await screen.findByText('Not connected');
  fireEvent.click(screen.getByRole('button'));
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
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveTextContent('did not respond in time');
  expect(screen.queryByText(/private-token-sentinel/)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button')).toBeEnabled());
});
