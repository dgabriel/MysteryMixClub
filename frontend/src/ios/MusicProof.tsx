import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  music,
  musicErrorMessage,
  isUncertainOutcome,
  nativeMusicAvailable,
  type Authorization,
  type MusicInspection,
  type PlaylistResult,
  type Reconciliation,
  type Session,
} from './music';

const labels: Record<Authorization, string> = {
  notDetermined: 'Not connected', authorized: 'Permission granted', denied: 'Permission denied',
  restricted: 'Access restricted on this device', unknown: 'Permission unavailable',
};

/** Which single action is in flight. The native bridge holds one lock across
 *  every method, so the UI models one too rather than a flag per button. */
type Action = 'signIn' | 'signOut' | 'connect' | 'build' | 'check' | 'open';

const button =
  'min-h-12 w-full rounded-hair px-4 py-3 font-mono text-label uppercase tracking-mono ' +
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent ' +
  // Disabled drops the box entirely rather than fading it: on a near-black page
  // opacity flattens a control into the background instead of quieting it.
  'disabled:bg-transparent disabled:text-muted-foreground disabled:cursor-not-allowed';
const primaryButton = `${button} bg-accent text-accent-foreground hover:bg-accent-hover`;
const ghostButton =
  `${button} border border-hairline bg-tile text-foreground hover:bg-panel disabled:border-transparent`;

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = `${title.toLowerCase().replace(/\s+/g, '-')}-heading`;
  return (
    <section className="space-y-5 rounded-tile bg-card p-6 shadow-z2" aria-labelledby={id}>
      <h2 id={id} className="font-display text-2xl font-bold tracking-display-snug">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, hint, ...props }: {
  label: string;
  hint?: string;
  type?: string;
  value: string;
  autoComplete?: string;
  inputMode?: 'email' | 'url' | 'text';
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const { onChange, ...rest } = props;
  const id = `field-${label.toLowerCase().replace(/\s+/g, '-')}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block font-mono text-mini uppercase tracking-mono text-muted-foreground">
        {label}
      </label>
      <input
        {...rest}
        id={id}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        onChange={event => onChange(event.target.value)}
        // Underline only, never a border box. text-base keeps iOS from zooming
        // the page on focus, which a smaller size would.
        className="min-h-12 w-full rounded-none border-0 border-b border-hairline bg-transparent
          text-base text-foreground focus:border-accent focus:outline-none disabled:text-muted-foreground"
      />
      {hint && <p className="text-meta leading-relaxed text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function MusicProof() {
  const native = nativeMusicAvailable();
  const [authorization, setAuthorization] = useState<Authorization>('unknown');
  const [inspection, setInspection] = useState<MusicInspection | null>(null);
  const [session, setSession] = useState<Session>({ signedIn: false });
  const [apiBaseUrl, setApiBaseUrl] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mixId, setMixId] = useState('');
  const [playlist, setPlaylist] = useState<PlaylistResult | null>(null);
  const [reconciliation, setReconciliation] = useState<Reconciliation | null>(null);
  // A build that never answered. Its result is unknown, not failed, so building
  // again is exactly the wrong next move.
  const [unresolved, setUnresolved] = useState(false);
  const [handoff, setHandoff] = useState(false);
  const [action, setAction] = useState<Action | null>(null);
  const [message, setMessage] = useState('');
  const running = useRef(false);
  const revision = useRef(0);
  const messageRef = useRef<HTMLParagraphElement>(null);

  // The message sits below every section, so on a phone it can render entirely
  // off-screen from wherever the action that caused it was tapped (confirmed on
  // device: a real failure message was there the whole time, just unseen below
  // the fold). Bring it into view rather than relying on a scroll to find it.
  useEffect(() => {
    if (!message) return;
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    messageRef.current?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  }, [message]);

  useEffect(() => {
    if (!native) return;
    let mounted = true;
    const refresh = () => {
      const current = ++revision.current;
      // Eligibility is a snapshot, and permission can change while the app is
      // away. Drop it rather than let a stale reading look current.
      setInspection(null);
      const apply = <T,>(next: Promise<T>, onValue: (value: T) => void, onError: () => void) => {
        void next.then(
          value => { if (mounted && current === revision.current) onValue(value); },
          () => { if (mounted && current === revision.current) onError(); },
        );
      };
      apply(music.status(), result => setAuthorization(result.authorization), () => setAuthorization('unknown'));
      apply(music.sessionStatus(), setSession, () => setSession({ signedIn: false }));
    };
    const resume = () => { if (document.visibilityState === 'visible') refresh(); };
    refresh();
    document.addEventListener('visibilitychange', resume);
    return () => { mounted = false; document.removeEventListener('visibilitychange', resume); };
  }, [native]);

  /** One action at a time, with the message cleared and the guard always released. */
  async function perform(next: Action, work: () => Promise<void>) {
    if (running.current) return;
    running.current = true;
    setAction(next);
    setMessage('');
    try {
      await work();
    } catch (error) {
      // Not Capacitor's own bridge logging (that stays off, capacitor.config.ts) --
      // this is our own, and is worth keeping in a device-test prototype: the
      // one way to see the raw shape a native rejection actually arrived in.
      console.error(`[ios-proof] ${next} failed:`, error);
      setMessage(musicErrorMessage(error));
    } finally {
      running.current = false;
      setAction(null);
    }
  }

  const connect = () => void perform('connect', async () => {
    setInspection(null);
    ++revision.current;
    const status = await music.authorize();
    setAuthorization(status.authorization);
    if (status.authorization !== 'authorized') return;
    const current = revision.current;
    const result = await music.inspect();
    if (current === revision.current) setInspection(result);
  });

  const signIn = () => void perform('signIn', async () => {
    setSession(await music.signIn({ apiBaseUrl, email, password }));
    // The password has been spent. Do not keep it in component state.
    setPassword('');
  });

  const signOut = () => void perform('signOut', async () => {
    setSession(await music.signOut());
    setPlaylist(null);
    setReconciliation(null);
    setUnresolved(false);
    setHandoff(false);
  });

  const build = () => void perform('build', async () => {
    setHandoff(false);
    setReconciliation(null);
    try {
      // getTimezoneOffset() is minutes to add to LOCAL to reach UTC; the server
      // wants the opposite, so negate it.
      const result = await music.createPlaylist({
        mixId, tzOffsetMinutes: -new Date().getTimezoneOffset(),
      });
      setPlaylist(result);
      setUnresolved(false);
    } catch (error) {
      setPlaylist(null);
      if (isUncertainOutcome(error)) setUnresolved(true);
      throw error;
    }
  });

  const check = () => void perform('check', async () => {
    const result = await music.reconcile({ mixId });
    setReconciliation(result);
    // The question is answered either way, so building is a decision again
    // rather than a blind retry.
    setUnresolved(false);
  });

  const openMusic = () => void perform('open', async () => {
    const result = await music.openMusic();
    setHandoff(result.opened);
    if (!result.opened) setMessage('This iPhone could not open Apple Music.');
  });

  const authorized = authorization === 'authorized';
  const mixGiven = mixId.trim().length > 0;
  const playlistName = playlist?.playlistName || reconciliation?.playlistName || '';
  const canBuild = native && !action && session.signedIn && authorized && mixGiven && !unresolved;

  return (
    <main className="ios-proof min-h-dvh bg-floor text-foreground">
      <div className="mx-auto max-w-lg space-y-8 px-6 py-10">
        <header className="space-y-3">
          <p className="font-mono text-xs uppercase tracking-mono-wide text-muted-foreground">Mystery Mix Club · iPhone proof</p>
          <h1 className="font-display text-5xl font-bold tracking-display-tight">Your music.<br />One connection.</h1>
          <p className="leading-relaxed text-muted-foreground">Connect to Apple Music using your iPhone’s permission dialog, then build this mix’s playlist in your library. Your credentials stay on your device.</p>
        </header>

        {!native && (
          <p role="status" className="rounded-tile bg-card p-6 leading-relaxed shadow-z2">
            Open this proof in the iPhone app. Nothing here works in a browser.
          </p>
        )}

        <Section title="Your account">
          {session.signedIn ? (
            <>
              <p role="status" aria-live="polite">
                Signed in as {session.displayName || session.email || 'this account'}.
              </p>
              <button type="button" className={ghostButton} disabled={!!action} onClick={signOut}>
                {action === 'signOut' ? 'Signing out' : 'Sign out'}
              </button>
            </>
          ) : (
            <>
              <p role="status" aria-live="polite">Not signed in.</p>
              <Field label="Server address" value={apiBaseUrl} onChange={setApiBaseUrl}
                inputMode="url" autoComplete="off" disabled={!native || !!action}
                hint="The backend this proof talks to, for example http://192.168.1.20:8000 on your own network." />
              <Field label="Email" type="email" value={email} onChange={setEmail}
                inputMode="email" autoComplete="username" disabled={!native || !!action} />
              <Field label="Password" type="password" value={password} onChange={setPassword}
                autoComplete="current-password" disabled={!native || !!action} />
              <button type="button" className={primaryButton} onClick={signIn}
                disabled={!native || !!action || !apiBaseUrl.trim() || !email.trim() || !password}>
                {action === 'signIn' ? 'Signing in' : 'Sign in'}
              </button>
            </>
          )}
        </Section>

        <Section title="Apple Music">
          <p role="status" aria-live="polite">{native ? labels[authorization] : 'Not available here.'}</p>
          {authorization === 'denied' && <p className="text-sm text-muted-foreground">Allow MMC iOS Proof under Settings → Privacy &amp; Security → Media &amp; Apple Music, then return here.</p>}
          {authorization === 'restricted' && <p className="text-sm text-muted-foreground">Device restrictions prevent access. Check Screen Time or contact the person managing this iPhone.</p>}
          <button type="button" className={primaryButton} disabled={!native || !!action} onClick={connect}>
            {action === 'connect' ? 'Checking Apple Music' : authorized ? 'Check connection' : 'Connect Apple Music'}
          </button>
          {inspection && <div role="status" className="space-y-3 text-sm leading-relaxed">
            <p>{inspection.canPlayCatalogContent ? 'Apple Music subscription is available.' : 'An eligible Apple Music subscription is needed for catalog access.'}</p>
            <p>{inspection.hasCloudLibraryEnabled ? 'Sync Library is enabled.' : 'Enable Sync Library in Apple Music settings before playlist testing.'}</p>
            <p>{inspection.tokenAvailable ? 'Native authorization token is available. Its value is not displayed or saved by this proof.' : 'A native authorization token is not available.'}</p>
          </div>}
        </Section>

        <Section title="Mix playlist">
          <Field label="Mix id" value={mixId} onChange={setMixId} disabled={!native || !!action}
            hint="The identifier in the mix page address on the web app." />

          {!session.signedIn && <p className="text-sm text-muted-foreground">Sign in above before building a playlist.</p>}
          {session.signedIn && !authorized && <p className="text-sm text-muted-foreground">Connect Apple Music above before building a playlist.</p>}

          {unresolved && (
            <p role="alert" className="rounded-hair border border-accent-hairline bg-accent-surface p-4 text-sm leading-relaxed">
              That build did not answer, so nobody knows whether it finished. Check this mix before building again. Building now could leave you with two playlists.
            </p>
          )}

          <button type="button" className={primaryButton} disabled={!canBuild} onClick={build}>
            {action === 'build' ? 'Building playlist' : playlistName ? 'Rebuild playlist' : 'Build playlist'}
          </button>
          <button type="button" className={ghostButton} onClick={check}
            disabled={!native || !!action || !session.signedIn || !mixGiven}>
            {action === 'check' ? 'Checking this mix' : 'Check this mix'}
          </button>

          {playlist && <div role="status" className="space-y-3 text-sm leading-relaxed">
            <p>Created <span className="font-mono">{playlist.playlistName}</span> with {playlist.trackCount} of {playlist.totalCount} tracks.</p>
            {playlist.unmatched.length > 0 && <>
              <p className="font-mono text-mini uppercase tracking-mono-wide text-muted-foreground">Not on this playlist</p>
              <ul className="space-y-2">
                {playlist.unmatched.map(track => (
                  <li key={`${track.title}-${track.artist}`}>
                    {track.title} by {track.artist}.{' '}
                    {track.reason === 'source_only'
                      ? 'Not in Apple Music’s catalog, so it was skipped rather than guessed at.'
                      : 'Apple Music’s catalog does not carry this track in your storefront.'}
                  </li>
                ))}
              </ul>
            </>}
          </div>}

          {reconciliation && <div role="status" className="space-y-3 text-sm leading-relaxed">
            {!reconciliation.serverHasRecord
              ? <p>No playlist has been created for this mix yet. It is safe to build one.</p>
              : <>
                  <p>Mystery Mix Club has a playlist on record for this mix, named <span className="font-mono">{reconciliation.playlistName}</span>.</p>
                  <p>{reconciliation.found
                    ? `This iPhone’s library has it, with ${reconciliation.trackCount ?? 0} tracks.`
                    : 'It is not in this iPhone’s library yet. Sync Library may still be catching up.'}</p>
                  {reconciliation.matchCount > 1 && <p>More than one playlist here carries that name.</p>}
                </>}
          </div>}

          {playlistName && <>
            <button type="button" className={ghostButton} disabled={!native || !!action} onClick={openMusic}>
              {action === 'open' ? 'Opening Apple Music' : 'Open Apple Music'}
            </button>
            {handoff && <p role="status" className="text-sm leading-relaxed text-muted-foreground">
              Apple Music opened. Find <span className="font-mono">{playlistName}</span> under Library, then Playlists. This proof cannot tell whether you got there.
            </p>}
          </>}
        </Section>

        {message && <p ref={messageRef} role="alert" className="rounded-tile bg-card p-6 text-sm leading-relaxed shadow-z2">{message}</p>}

        <p className="text-sm leading-relaxed text-muted-foreground">Nothing on this screen stores a password, an Apple Music token, or a Mystery Mix Club token where JavaScript can read it.</p>
      </div>
    </main>
  );
}
