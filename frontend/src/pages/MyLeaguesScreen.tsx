import type { League } from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { CrownIcon } from "../components/CrownIcon";
import { SongSearchCard } from "../components/songs/SongSearchCard";

type MyLeaguesScreenProps = {
  displayName: string | null;
  leagues: League[];
  loading: boolean;
  error?: string | null;
  preferredService?: string | null;
  onCreateLeague: () => void;
  onOpenLeague: (id: string) => void;
};

export function MyLeaguesScreen({
  displayName,
  leagues,
  loading,
  error,
  preferredService,
  onCreateLeague,
  onOpenLeague,
}: MyLeaguesScreenProps) {
  const activeLeagues = leagues.filter((l) => l.state !== "complete");
  const completedLeagues = leagues.filter((l) => l.state === "complete");
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
                <p className="mt-8 font-mono text-[13px] font-light text-muted">no clubs yet</p>
                <div className="mt-6">
                  <Button type="button" onClick={onCreateLeague}>
                    create a club
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
                  my clubs
                </h1>

                <div className="mt-4">
                  <Button type="button" onClick={onCreateLeague}>
                    create a club
                  </Button>
                </div>

                {error ? (
                  <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
                    {error}
                  </p>
                ) : null}

                {/* Active leagues first; completed ones drop below under their
                    own heading with the gold achievement treatment (MYS-149). */}
                <ul className="mt-8 space-y-4">
                  {activeLeagues.map((league) => (
                    <li key={league.id}>
                      <LeagueCard league={league} complete={false} onOpen={onOpenLeague} />
                    </li>
                  ))}
                </ul>

                {completedLeagues.length > 0 ? (
                  <section className="mt-10">
                    <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
                      completed
                    </h2>
                    <ul className="mt-4 space-y-4">
                      {completedLeagues.map((league) => (
                        <li key={league.id}>
                          <LeagueCard league={league} complete onOpen={onOpenLeague} />
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </>
            )}

            {/* Permanent home-screen fixture, below the league list (MYS-45). */}
            <section className="mt-12 border-t border-border pt-10">
                <h2 className="mt-1 font-serif lowercase text-[18px] leading-tight text-ink">
                  practice your song search skills here — no club required
                </h2> 
                <br/>             
              <SongSearchCard preferredService={preferredService} />
            </section>
          </div>
        )}
    </main>
  );
}

/** A league row on the home list. Completed leagues wear the gold achievement
 *  treatment — a crown by the eyebrow and a thin gold left accent — matching the
 *  reveal's winner/most-noted moments (MYS-149). Active leagues stay in the
 *  Sage family with no accent. */
function LeagueCard({
  league,
  complete,
  onOpen,
}: {
  league: League;
  complete: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <Card
      className={`transition-colors duration-150 hover:bg-sage-pale${
        complete ? " border-l-[3px] border-l-gold" : ""
      }`}
    >
      <button type="button" onClick={() => onOpen(league.id)} className="block w-full text-left">
        <span className="flex items-center gap-1.5 font-mono uppercase tracking-label text-[9px] text-muted">
          {complete ? <CrownIcon className="text-gold" /> : null}
          club
        </span>
        <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">{league.name}</h2>
        <div className="mt-3 flex items-center justify-between">
          <span className="font-mono text-[11px] font-light text-muted">
            mix {league.current_round} of {league.total_rounds}
          </span>
          <Badge>{league.state}</Badge>
        </div>
      </button>
    </Card>
  );
}
