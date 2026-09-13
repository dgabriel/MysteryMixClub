import { useEffect, useRef, useState } from 'react';
import { music, musicErrorMessage, nativeMusicAvailable, type MusicInspection, type Authorization } from './music';

const labels: Record<Authorization, string> = {
  notDetermined: 'Not connected', authorized: 'Permission granted', denied: 'Permission denied',
  restricted: 'Access restricted on this device', unknown: 'Permission unavailable',
};

export function MusicProof() {
  const native = nativeMusicAvailable();
  const [authorization, setAuthorization] = useState<Authorization>('unknown');
  const [inspection, setInspection] = useState<MusicInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const running = useRef(false);
  const revision = useRef(0);

  useEffect(() => {
    if (!native) return;
    let mounted = true;
    const refresh = () => {
      const current = ++revision.current;
      setInspection(null);
      void music.status().then(result => {
        if (mounted && current === revision.current) setAuthorization(result.authorization);
      }).catch(() => {
        if (mounted && current === revision.current) setAuthorization('unknown');
      });
    };
    const resume = () => { if (document.visibilityState === 'visible') refresh(); };
    refresh();
    document.addEventListener('visibilitychange', resume);
    return () => { mounted = false; document.removeEventListener('visibilitychange', resume); };
  }, [native]);

  async function connect() {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setMessage('');
    setInspection(null);
    ++revision.current;
    try {
      const status = await music.authorize();
      setAuthorization(status.authorization);
      if (status.authorization === 'authorized') {
        const current = revision.current;
        const result = await music.inspect();
        if (current === revision.current) setInspection(result);
      }
    } catch (error) {
      setMessage(musicErrorMessage(error));
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="ios-proof min-h-dvh bg-floor text-foreground">
      <div className="mx-auto max-w-lg space-y-8 px-6 py-10">
        <header className="space-y-3">
          <p className="font-mono text-xs uppercase tracking-mono-wide text-muted-foreground">Mystery Mix Club · iPhone proof</p>
          <h1 className="font-display text-5xl font-bold tracking-display-tight">Your music.<br />One connection.</h1>
          <p className="leading-relaxed text-muted-foreground">Connect to Apple Music using your iPhone’s permission dialog. Your music credentials stay on your device.</p>
        </header>
        <section className="space-y-5 rounded-tile bg-card p-6 shadow-z2" aria-labelledby="connection-heading">
          <h2 id="connection-heading" className="font-display text-2xl font-bold">Apple Music</h2>
          <p role="status" aria-live="polite">{native ? labels[authorization] : 'Open this proof in the iPhone app to connect.'}</p>
          {authorization === 'denied' && <p className="text-sm text-muted-foreground">Allow MMC iOS Proof under Settings → Privacy &amp; Security → Media &amp; Apple Music, then return here.</p>}
          {authorization === 'restricted' && <p className="text-sm text-muted-foreground">Device restrictions prevent access. Check Screen Time or contact the person managing this iPhone.</p>}
          <button type="button" disabled={!native || busy} onClick={() => void connect()}
            className="min-h-12 w-full rounded-hair bg-accent px-4 py-3 font-medium text-accent-foreground hover:bg-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent disabled:opacity-50">
            {busy ? 'Checking Apple Music…' : authorization === 'authorized' ? 'Check connection' : 'Connect Apple Music'}
          </button>
          {message && <p role="alert" className="text-sm leading-relaxed">{message}</p>}
          {inspection && <div role="status" className="space-y-3 text-sm leading-relaxed">
            <p>{inspection.canPlayCatalogContent ? 'Apple Music subscription is available.' : 'An eligible Apple Music subscription is needed for catalog access.'}</p>
            <p>{inspection.hasCloudLibraryEnabled ? 'Sync Library is enabled.' : 'Enable Sync Library in Apple Music settings before playlist testing.'}</p>
            <p>{inspection.tokenAvailable ? 'Native authorization token is available. Its value is not displayed or saved by this proof.' : 'A native authorization token is not available.'}</p>
          </div>}
        </section>
        <p className="text-sm leading-relaxed text-muted-foreground">This first device check does not create a playlist or sign in to MMC. Playlist creation and returning to your mix are the next integration step.</p>
      </div>
    </main>
  );
}
