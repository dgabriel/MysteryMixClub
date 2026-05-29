import { Button } from "../components/Button";
import { ConcentricRings } from "../components/ConcentricRings";

type HomeScreenProps = {
  onLogout: () => void;
  onLogoutAll: () => void;
  busy?: boolean;
};

export function HomeScreen({ onLogout, onLogoutAll, busy = false }: HomeScreenProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="flex items-center justify-between px-4 py-4 sm:px-8">
        <span className="font-mono uppercase tracking-ui text-[11px] text-ink">
          mysterymixclub
        </span>
        <Button variant="ghost" type="button" onClick={onLogout} disabled={busy}>
          logout
        </Button>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-4 sm:px-8">
        <div className="w-full max-w-sm text-center">
          {/* Motif without the Rust dot — the one Rust use is the settings link. */}
          <ConcentricRings size={88} className="mx-auto" />
          <h1 className="mt-8 font-serif text-[34px] leading-tight">you’re in</h1>
          <p className="mt-2 font-mono text-[13px] font-light text-muted">
            your rounds will appear here soon.
          </p>
        </div>
      </main>

      <footer className="border-t border-border px-4 py-6 sm:px-8">
        <div className="mx-auto w-full max-w-sm">
          <p className="font-mono uppercase tracking-label text-[9px] text-muted">
            settings
          </p>
          <div className="mt-3">
            {/* The screen's one Rust use — the heavier session action. */}
            <Button variant="link" type="button" onClick={onLogoutAll} disabled={busy}>
              log out of all devices
            </Button>
          </div>
        </div>
      </footer>
    </div>
  );
}
