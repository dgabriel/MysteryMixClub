import type { League } from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { SongSearchCard } from "../components/songs/SongSearchCard";

type MyLeaguesScreenProps = {
  displayName: string | null;
  leagues: League[];
  loading: boolean;
  error?: string | null;
  onCreateLeague: () => void;
  onOpenLeague: (id: string) => void;
};

export function MyLeaguesScreen({
  displayName,
  leagues,
  loading,
  error,
  onCreateLeague,
  onOpenLeague,
}: MyLeaguesScreenProps) {
  return (
    // The shared TopNav is rendered by AuthedLayout; this screen is just content.
    <main className="flex flex-1 flex-col px-4 py-8 sm:px-8">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            {/* Loading motif — no Rust dot. */}
            <ConcentricRings size={88} spinning className="mx-auto" />
          </div>
        ) : (
          <div className="mx-auto w-full max-w-lg">
            {leagues.length === 0 ? (
              <div className="flex flex-col items-center pt-4 text-center">
                {/* Empty state — the screen's one Rust use is the off-center ring dot. */}
                <ConcentricRings size={88} accent className="mx-auto" />
                <p className="mt-8 font-mono text-[13px] font-light text-muted">no leagues yet</p>
                <div className="mt-6">
                  <Button type="button" onClick={onCreateLeague}>
                    create a league
                  </Button>
                </div>
                {error ? (
                  <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
                    {error}
                  </p>
                ) : null}
              </div>
            ) : (
              <>
                {displayName ? (
                  <p className="font-mono uppercase tracking-label text-[9px] text-muted">
                    {displayName}
                  </p>
                ) : null}
                <h1 className="mt-1 font-serif lowercase text-[28px] leading-tight text-ink">
                  my leagues
                </h1>

                <div className="mt-4">
                  <Button type="button" onClick={onCreateLeague}>
                    create a league
                  </Button>
                </div>

                {error ? (
                  <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
                    {error}
                  </p>
                ) : null}

                <ul className="mt-8 space-y-4">
                  {leagues.map((league) => (
                    <li key={league.id}>
                      {/* Default (Sage) badge only — no Rust on populated cards. */}
                      <Card className="transition-colors duration-150 hover:bg-sage-pale">
                        <button
                          type="button"
                          onClick={() => onOpenLeague(league.id)}
                          className="block w-full text-left"
                        >
                          <span className="font-mono uppercase tracking-label text-[9px] text-muted">
                            league
                          </span>
                          <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">
                            {league.name}
                          </h2>
                          <div className="mt-3 flex items-center justify-between">
                            <span className="font-mono text-[11px] font-light text-muted">
                              round {league.current_round} of {league.total_rounds}
                            </span>
                            <Badge>{league.state}</Badge>
                          </div>
                        </button>
                      </Card>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {/* Permanent home-screen fixture, below the league list (MYS-45). */}
            <section className="mt-12 border-t border-border pt-10">
              <SongSearchCard />
            </section>
          </div>
        )}
    </main>
  );
}
