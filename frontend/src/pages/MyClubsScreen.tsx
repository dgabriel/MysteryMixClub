import type { Club } from "../services/api";
import { Button } from "../components/Button";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ClubName } from "../components/ClubName";
import { ConcentricRings } from "../components/ConcentricRings";
import { CrownIcon } from "../components/CrownIcon";
import { HelpLink } from "../components/HelpLink";
import { PaperSurface } from "../components/PaperSurface";
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
    //
    // The first authed screen on the light surface (ADR 0013). The frame model:
    // the page is `paper`, the cards stay dark. That composes here without
    // touching a single card interior — every ClubCard goes through the dark
    // `Card` primitive and SongSearchCard renders its own — so only the chrome
    // sitting directly on the page moves to the `ink` ramp.
    <PaperSurface nested>
      <main className="flex flex-1 flex-col px-4 py-8 sm:px-8">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            {/* Loading motif — the disc spins, neutral. The amber centre label
                is the brand mark and belongs to the empty state's hero below;
                a spinner is not an identity placement. */}
            <ConcentricRings size={88} spinning onPaper className="mx-auto" />
          </div>
        ) : (
          <div className="mx-auto w-full max-w-lg">
            {clubs.length === 0 ? (
              <div className="flex flex-col items-center pt-4 text-center">
                {/* Empty state — the screen's one amber hero mark. ADR 0010
                    bounds amber-as-identity to the shared nav's persistent 28px
                    mark (rendered by AuthedLayout's TopNav) plus at most one
                    hero mark in a screen's own content, and MyClubsScreen is
                    named there. It qualifies as a hero rather than decoration:
                    with no clubs it is the only object on the screen, at the
                    88px page-hero size, and the loading disc it replaces can
                    never render at the same time. */}
                <ConcentricRings size={88} accent onPaper className="mx-auto" />
                <span className="mt-8 flex items-center gap-2">
                  <p className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
                    no clubs yet
                  </p>
                  <HelpLink anchor="clubs" onPaper />
                </span>
                <div className="mt-6">
                  <Button type="button" onClick={onCreateClub}>
                    create a club
                  </Button>
                </div>
                {error ? (
                  <p role="alert" className="mt-6 text-sm leading-[1.72] text-ink">
                    {error}
                  </p>
                ) : null}
              </div>
            ) : (
              <>
                {/* The signed-in user's own name, in amber: the eyebrow answers
                    "whose clubs are these", so it is marking something rather
                    than decorating. Note this is the *viewer's own* name — other
                    people's names (submitters, voters, members) stay muted, so
                    amber here reads as "you". That's a content judgement, not a
                    rule: amber placement is a design decision (ADR 0012).
                    `ink-accent` rather than `accent` now the page is paper —
                    at 9.6px this is body-size text, so it owes the full 4.5:1
                    and `accent` would be 2.62:1. */}
                {displayName ? (
                  <p className="font-mono text-mini uppercase tracking-mono-caps text-ink-accent">
                    {displayName}
                  </p>
                ) : null}
                <span className="mt-1 flex items-center gap-2">
                  <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug">
                    my clubs
                  </h1>
                  <HelpLink anchor="clubs" onPaper />
                </span>

                <div className="mt-4">
                  <Button type="button" onClick={onCreateClub}>
                    create a club
                  </Button>
                </div>

                {error ? (
                  <p role="alert" className="mt-6 text-sm leading-[1.72] text-ink">
                    {error}
                  </p>
                ) : null}

                {/* Active clubs first; completed ones drop below under their
                    own heading with the crown achievement marker (MYS-149). */}
                <ul className="mt-8 space-y-4">
                  {activeClubs.map((club) => (
                    <li key={club.id}>
                      <ClubCard
                        club={club}
                        complete={false}
                        isAdmin={club.viewer_is_admin === true}
                        onOpen={onOpenClub}
                      />
                    </li>
                  ))}
                </ul>

                {completedClubs.length > 0 ? (
                  <section className="mt-10">
                    <h2 className="font-mono text-meta uppercase tracking-mono-wide text-ink-muted">
                      completed
                    </h2>
                    <ul className="mt-4 space-y-4">
                      {completedClubs.map((club) => (
                        <li key={club.id}>
                          <ClubCard
                            club={club}
                            complete
                            isAdmin={club.viewer_is_admin === true}
                            onOpen={onOpenClub}
                          />
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}
              </>
            )}

            {/* Permanent home-screen fixture, below the club list (MYS-45). */}
            <section className="mt-12 border-t border-ink-hairline pt-10">
              <p className="mt-1 text-base leading-[1.72] text-ink">
                practice your song search skills here — no club required
              </p>
              <SongSearchCard preferredService={preferredService} />
            </section>
          </div>
        )}
      </main>
    </PaperSurface>
  );
}

/** A club row on the home list, and the pattern every later list screen follows:
 *  a `card` surface at `shadow-z2` lifting to `shadow-z3` on hover, a mono
 *  eyebrow, a `font-display` uppercase item title, and a mono metadata row.
 *
 *  The lift is the whole hover treatment and it is pure CSS — `hover:` on the
 *  card wrapper, no JS hover state — which is what lets the row stay a plain
 *  button rather than a stateful component.
 *
 *  **Neither state carries amber, and that is the whole colour argument here.**
 *  `GET /clubs` returns every club the user is an active member of, with no
 *  pagination, no cap, and no way to archive one — so both sets are unbounded
 *  and only grow. Amber on the *completed* set would paint a column of amber on
 *  a long-lived account; amber on the *active* set is worse, because active is
 *  the default state and would be true of nearly every row. Either way the
 *  colour would stop marking anything, which is the one rule ADR 0012 still
 *  enforces.
 *
 *  So: **active takes `positive` (green), and amber is reserved for the admin
 *  chip**, which genuinely varies — you organise some of your clubs, not all.
 *  Completion stays carried by three neutral signals that don't degrade with
 *  count: the "completed" section heading, the crown glyph, and the state Badge
 *  reading "complete".
 *
 *  **Colour is never the sole signal.** The bar is `aria-hidden` decoration; the
 *  state is in the Badge's text and the admin role is the word "admin". */
function ClubCard({
  club,
  complete,
  isAdmin,
  onOpen,
}: {
  club: Club;
  complete: boolean;
  isAdmin: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <Card
      bar={complete ? undefined : "positive"}
      className="transition-[box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:shadow-z3"
    >
      <button type="button" onClick={() => onOpen(club.id)} className="block w-full text-left">
        {/* The card's chrome recedes to `subtle-foreground` so the club name has
            somewhere to be prominent from. Everything here used to sit at
            `muted-foreground` within a 9.6-14px band — eyebrow, name, counter
            and badge all one rank, which is what made the list read as uniform.
            The name is the thing you scan for, so it takes the display face at a
            size the rest of the card doesn't reach. */}
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-1.5 font-mono text-mini uppercase tracking-mono-caps text-subtle-foreground">
            {complete ? <CrownIcon className="text-subtle-foreground" /> : null}
            club
          </span>
          {/* Amber, and selective: this is the one marker on the card that is
              true of some rows and not others, which is exactly what the accent
              is for. It sits opposite the eyebrow rather than beside the state
              Badge so role and state stay two separate readings. */}
          {isAdmin ? <Badge variant="accent">admin</Badge> : null}
        </div>
        <h2 className="mt-2 font-display text-[1.375rem] font-bold uppercase leading-none tracking-display-snug">
          <ClubName name={club.name} />
        </h2>
        <div className="mt-4 flex items-center justify-between">
          <span className="font-mono text-meta text-subtle-foreground">
            mix {club.current_mix} of {club.total_mixes}
          </span>
          <Badge>{club.state}</Badge>
        </div>
      </button>
    </Card>
  );
}
