import { Fragment, useMemo, useState } from "react";
import type { MySubmission } from "../services/api";
import { PaperSurface } from "../components/PaperSurface";
import { TextField } from "../components/TextField";
import { Badge } from "../components/Badge";
import { ClubName } from "../components/ClubName";
import { SourceBadge } from "../components/SourceBadge";
import { ConcentricRings } from "../components/ConcentricRings";
import { MIX_BADGE, MIX_STATE_LABEL, mixGroup } from "../utils/mixState";

type SortKey = "newest" | "title" | "artist" | "club";

function matchesQuery(entry: MySubmission, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return entry.title.toLowerCase().includes(q) || entry.artist.toLowerCase().includes(q);
}

function sortEntries(entries: MySubmission[], sort: SortKey): MySubmission[] {
  const sorted = [...entries];
  switch (sort) {
    case "title":
      sorted.sort((a, b) => a.title.localeCompare(b.title));
      break;
    case "artist":
      sorted.sort((a, b) => a.artist.localeCompare(b.artist));
      break;
    case "club":
      sorted.sort(
        (a, b) => a.club_name.localeCompare(b.club_name) || a.mix_number - b.mix_number,
      );
      break;
    case "newest":
    default:
      sorted.sort((a, b) => b.created_at.localeCompare(a.created_at));
      break;
  }
  return sorted;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Column headers that double as sort triggers. `field` matches a `SortKey`;
 *  the votes/notes columns have nothing to sort by, so they're plain `<th>`s
 *  below. */
const SORTABLE_COLUMNS: { field: SortKey; label: string }[] = [
  { field: "title", label: "song" },
  { field: "artist", label: "artist" },
  { field: "club", label: "club" },
  { field: "newest", label: "date" },
];

/** Small line chevron, rotates on expand. 1.25px stroke, matching the
 *  iconography spec (TopNav's BackIcon uses the same weight). */
function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={`shrink-0 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
    >
      <path d="M6 3l5 5-5 5" />
    </svg>
  );
}

/**
 * Every song the caller has ever submitted, across every club
 * (MysteryMixClub-ps1w.1) -- a sortable/searchable grid: song, artist, club,
 * mix, date, vote count, note count. Each row expands (closed by default)
 * into a preview with the fuller detail a grid cell can't hold (art, the
 * submitter's own note, the notes thread, voter names, the mix's theme and
 * state).
 *
 * Filtering/sorting happen client-side over the one list `GET
 * /users/me/submissions` returns -- there's no pagination convention
 * elsewhere in this app, and its invite-only, friend-group scale doesn't
 * call for one here.
 *
 * Renders on the light `paper` surface (ADR 0013): the grid itself is one
 * dark `card` island (ADR 0013's frame model -- a dark surface on a light
 * page anchors its own text colour), with `hairline-soft` row dividers and
 * `tile` for the nested expanded-preview panel (the elevation step the style
 * guide reserves for "an inset chip inside a card").
 *
 * Vote identity and other players' notes follow the exact same visibility
 * rules the backend already enforces (MYS-173 / MYS-67) -- this screen has no
 * client-side gating logic of its own to get wrong, it just renders whatever
 * the API decided to reveal.
 */
export function SubmissionHistoryScreen({
  entries,
  loading,
  error,
  onOpenMix,
}: {
  entries: MySubmission[];
  loading: boolean;
  error?: string | null;
  onOpenMix: (mixId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [expanded, setExpanded] = useState<string | null>(null);

  const visible = useMemo(
    () => sortEntries(entries.filter((e) => matchesQuery(e, query)), sort),
    [entries, query, sort],
  );

  if (loading) {
    return (
      <PaperSurface nested>
        <main className="flex flex-1 items-center justify-center px-4 sm:px-8">
          <ConcentricRings size={88} spinning onPaper className="mx-auto" />
        </main>
      </PaperSurface>
    );
  }

  return (
    <PaperSurface nested>
      <main className="mx-auto w-full max-w-4xl px-4 pt-8 pb-16 sm:px-8">
        <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug text-ink">
          my submissions
        </h1>

        {error ? (
          <p role="alert" className="mt-6 text-sm leading-[1.72] text-ink">
            {error}
          </p>
        ) : (
          <>
            <div className="mt-8 max-w-sm">
              <TextField
                onPaper
                id="submission-history-search"
                label="search"
                type="search"
                name="submission-history-search"
                autoComplete="off"
                placeholder="title or artist"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {entries.length === 0 ? (
              <p className="mt-8 text-sm leading-[1.72] text-ink-muted">
                you haven&apos;t submitted a song yet.
              </p>
            ) : visible.length === 0 ? (
              <p className="mt-8 text-sm leading-[1.72] text-ink-muted">
                no songs match &ldquo;{query}&rdquo;.
              </p>
            ) : (
              <SubmissionGrid
                entries={visible}
                sort={sort}
                onSort={setSort}
                expanded={expanded}
                onToggle={(id) => setExpanded((cur) => (cur === id ? null : id))}
                onOpenMix={onOpenMix}
              />
            )}
          </>
        )}
      </main>
    </PaperSurface>
  );
}

function SubmissionGrid({
  entries,
  sort,
  onSort,
  expanded,
  onToggle,
  onOpenMix,
}: {
  entries: MySubmission[];
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  expanded: string | null;
  onToggle: (id: string) => void;
  onOpenMix: (mixId: string) => void;
}) {
  return (
    <div className="mt-6 overflow-hidden rounded-tile border border-hairline bg-card shadow-z2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[800px] border-collapse text-foreground">
          <thead>
            <tr className="border-b border-hairline">
              <th scope="col" className="w-10 px-4 py-3">
                <span className="sr-only">expand</span>
              </th>
              {SORTABLE_COLUMNS.map((col) => (
                <th key={col.field} scope="col" className="px-2 py-3 text-left">
                  <button
                    type="button"
                    onClick={() => onSort(col.field)}
                    aria-pressed={sort === col.field}
                    className={[
                      "font-mono uppercase tracking-mono-caps text-mini transition-colors duration-150",
                      sort === col.field
                        ? "text-foreground underline underline-offset-[3px]"
                        : "text-muted-foreground hover:text-foreground",
                    ].join(" ")}
                  >
                    {col.label}
                  </button>
                </th>
              ))}
              <th
                scope="col"
                className="px-2 py-3 text-right font-mono uppercase tracking-mono-caps text-mini text-muted-foreground"
              >
                mix
              </th>
              <th
                scope="col"
                className="px-2 py-3 text-right font-mono uppercase tracking-mono-caps text-mini text-muted-foreground"
              >
                votes
              </th>
              <th
                scope="col"
                className="px-4 py-3 text-right font-mono uppercase tracking-mono-caps text-mini text-muted-foreground"
              >
                notes
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const open = expanded === entry.submission_id;
              return (
                <Fragment key={entry.submission_id}>
                  <tr
                    onClick={() => onToggle(entry.submission_id)}
                    className="cursor-pointer border-b border-hairline-soft transition-colors duration-150 last:border-b-0 hover:bg-tile/50"
                  >
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-label={`${open ? "hide" : "show"} details for ${entry.title}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggle(entry.submission_id);
                        }}
                        className="flex items-center justify-center text-muted-foreground transition-colors duration-150 hover:text-foreground"
                      >
                        <ChevronIcon open={open} />
                      </button>
                    </td>
                    <td className="px-2 py-3 font-display text-sm font-bold uppercase leading-none">
                      {entry.title}
                    </td>
                    <td className="px-2 py-3 font-mono text-mini text-muted-foreground">
                      {entry.artist}
                    </td>
                    <td className="px-2 py-3 text-sm">
                      <ClubName name={entry.club_name} />
                    </td>
                    <td className="px-2 py-3 font-mono text-mini text-muted-foreground">
                      {formatDate(entry.created_at)}
                    </td>
                    <td className="px-2 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.mix_number}
                    </td>
                    <td className="px-2 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.vote_count !== null ? entry.vote_count : "hidden"}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.notes.length}
                    </td>
                  </tr>
                  {open ? (
                    <tr className="border-b border-hairline-soft last:border-b-0">
                      <td colSpan={8} className="bg-tile px-4 py-4">
                        <SubmissionPreview entry={entry} onOpenMix={onOpenMix} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The detail a grid cell can't hold: art, the mix's theme/state, the
 *  submitter's own note, who voted (once revealed), and the notes thread.
 *  Shown in full once expanded -- no further collapsing behind a second
 *  disclosure, since the row toggle above is already the "closed by
 *  default" gate the design calls for. */
function SubmissionPreview({
  entry,
  onOpenMix,
}: {
  entry: MySubmission;
  onOpenMix: (mixId: string) => void;
}) {
  return (
    <div className="flex items-start gap-4">
      <span className="relative block shrink-0" style={{ width: 56, height: 56 }}>
        <span aria-hidden="true" className="block h-full w-full rounded-hair bg-panel" />
        {entry.album_art_url ? (
          <img
            src={entry.album_art_url}
            alt={`${entry.title} album art`}
            width={56}
            height={56}
            className="absolute rounded-hair object-cover shadow-art"
            style={{ width: 56, height: 56, top: -4, left: -4 }}
          />
        ) : null}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            mix {entry.mix_number}
            {entry.theme ? ` · ${entry.theme}` : ""}
          </span>
          <div className="flex items-center gap-2">
            <Badge variant={MIX_BADGE[mixGroup(entry.state)]}>{MIX_STATE_LABEL[entry.state]}</Badge>
            <button
              type="button"
              onClick={() => onOpenMix(entry.mix_id)}
              className="font-mono uppercase tracking-mono text-label text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link"
            >
              open mix
            </button>
          </div>
        </div>

        {entry.source ? (
          <div className="mt-2">
            <SourceBadge source={entry.source} />
          </div>
        ) : null}

        {entry.submitter_note ? (
          <p className="mt-2 text-meta leading-[1.6] text-foreground">
            &ldquo;{entry.submitter_note}&rdquo;
          </p>
        ) : null}

        {entry.vote_count !== null ? (
          entry.voters.length > 0 ? (
            <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
              voted by{" "}
              {entry.voters
                .map((v) => (v.weight > 1 ? `${v.display_name} ×${v.weight}` : v.display_name))
                .join(", ")}
            </p>
          ) : null
        ) : (
          <p className="mt-2 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
            votes reveal once this mix closes
          </p>
        )}

        {entry.notes.length > 0 ? (
          <ul className="mt-3 space-y-3 border-t border-hairline-soft pt-3">
            {entry.notes.map((note, i) => (
              <li key={i}>
                <p className="text-sm leading-[1.65] text-foreground">{note.body}</p>
                <span className="mt-1 block font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  {note.author_display_name}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
