import type { Club } from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConcentricRings } from "../components/ConcentricRings";
import { CrownIcon } from "../components/CrownIcon";
import { HelpLink } from "../components/HelpLink";
import { SongSearchCard } from "../components/songs/SongSearchCard";

type MyClubsScreenProps = {
  displayName: string | null;
  clubs: Club[];
  loading: boolean;
  error?: string | null;
  preferredService?: string | null;
  onCreateClub: () => void;
  onOpenClub: (id: string) => void;
};

export function MyClubsScreen({
  displayName,
  clubs,
  loading,
  error,
  preferredService,
  onCreateClub,
  onOpenClub,
}: MyClubsScreenProps) {
  const activeClubs = clubs.filter((l) => l.state !== "complete");
  const completedClubs = clubs.filter((l) => l.state === "complete");
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
            {clubs.length === 0 ? (
              <div className="flex flex-col items-center pt-4 text-center">
                {/* Empty state — the screen's one Rust use is the off-center ring dot. */}
                <ConcentricRings size={88} accent className="mx-auto" />
                <span className="mt-8 flex items-center gap-2">
                  <p className="font-mono text-[13px] font-light text-muted">no clubs yet</p>
                  <HelpLink anchor="clubs" />
                </span>
                <div className="mt-6">
                  <Button type="button" onClick={onCreateClub}>
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
                <span className="mt-1 flex items-center gap-2">
                  <h1 className="font-serif lowercase text-[28px] leading-tight text-ink">
                    my clubs
                  </h1>
                  <HelpLink anchor="clubs" />
                </span>

                <div className="mt-4">
                  <Button type="button" onClick={onCreateClub}>
                    create a club
                  </Button>
                </div>

                {error ? (
                  <p role="alert" className="mt-6 font-mono text-[11px] text-ink">
                    {error}
                  </p>
                ) : null}

                {/* Active clubs first; completed ones drop below under their
                    own heading with the gold achievement treatment (MYS-149). */}
                <ul className="mt-8 space-y-4">
                  {activeClubs.map((club) => (
                    <li key={club.id}>
                      <ClubCard club={club} complete={false} onOpen={onOpenClub} />
                    </li>
                  ))}
                </ul>

                {completedClubs.length > 0 ? (
                  <section className="mt-10">
                    <h2 className="font-mono uppercase tracking-label text-[9px] text-muted">
                      completed
                    </h2>
                    <ul className="mt-4 space-y-4">
                      {completedClubs.map((club) => (
                        <li key={club.id}>
                          <ClubCard club={club} complete onOpen={onOpenClub} />
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </>
            )}

            {/* Permanent home-screen fixture, below the club list (MYS-45). */}
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

/** A club row on the home list. Completed clubs wear the gold achievement
 *  treatment — a crown by the eyebrow and a thin gold left accent — matching the
 *  reveal's winner/most-noted moments (MYS-149). Active clubs stay in the
 *  Sage family with no accent. */
function ClubCard({
  club,
  complete,
  onOpen,
}: {
  club: Club;
  complete: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <Card
      className={`group transition-colors duration-150 hover:bg-sage-pale${
        complete ? " border-l-[3px] border-l-gold" : ""
      }`}
    >
      <button type="button" onClick={() => onOpen(club.id)} className="block w-full text-left">
        <span className="flex items-center gap-1.5 font-mono uppercase tracking-label text-[9px] text-muted group-hover:text-sage">
          {complete ? <CrownIcon className="text-gold" /> : null}
          club
        </span>
        <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">{club.name}</h2>
        <div className="mt-3 flex items-center justify-between">
          <span className="font-mono text-[11px] font-light text-muted group-hover:text-sage">
            mix {club.current_mix} of {club.total_mixes}
          </span>
          <Badge>{club.state}</Badge>
        </div>
      </button>
    </Card>
  );
}
