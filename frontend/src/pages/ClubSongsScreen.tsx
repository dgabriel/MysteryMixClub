import { Fragment, useMemo, useState } from "react";
import type { ClubSong } from "../services/api";
import { PaperSurface } from "../components/PaperSurface";
import { TextField } from "../components/TextField";
import { SourceBadge } from "../components/SourceBadge";
import { ConcentricRings } from "../components/ConcentricRings";

type SortKey = "newest" | "title" | "artist" | "submitter";

function matchesQuery(entry: ClubSong, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return entry.title.toLowerCase().includes(q) || entry.artist.toLowerCase().includes(q);
}

function sortEntries(entries: ClubSong[], sort: SortKey): ClubSong[] {
  const sorted = [...entries];
  switch (sort) {
    case "title":
      sorted.sort((a, b) => a.title.localeCompare(b.title));
      break;
    case "artist":
      sorted.sort((a, b) => a.artist.localeCompare(b.artist));
      break;
    case "submitter":
      sorted.sort(
        (a, b) =>
          a.submitter_display_name.localeCompare(b.submitter_display_name) ||
          a.mix_number - b.mix_number,
      );
      break;
    case "newest":
    default:
      sorted.sort((a, b) => b.created_at.localeCompare(a.created_at));
      break;
  }
  return sorted;
}

const SORTABLE_COLUMNS: { field: SortKey; label: string }[] = [
  { field: "title", label: "song" },
  { field: "artist", label: "artist" },
  { field: "submitter", label: "submitter" },
  { field: "newest", label: "date" },
];

/** Small line chevron, rotates on expand -- shared shape with
 *  SubmissionHistoryScreen's, duplicated rather than hoisted (see that file's
 *  own AlbumArt/CollapsibleNotes duplication note). */
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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Every song ever submitted to this club, across its CLOSED mixes only
 * (MysteryMixClub-ps1w.2) -- a sortable/searchable grid: song, artist,
 * submitter, mix, vote count, note count. Each row expands (closed by
 * default) into a preview with album art, the mix's theme, the submitter's
 * own note, voter names, and the notes thread.
 *
 * The club's currently active mix doesn't appear here until it closes --
 * matches the existing GET /mixes/:id/submissions rule and MYS-173 vote
 * anonymity. Unlike /profile/history, vote/note data is never gated here:
 * every entry belongs to an already-closed mix, so the backend always
 * returns the full reveal.
 *
 * Same grid pattern as SubmissionHistoryScreen (approved on
 * MysteryMixClub-ps1w.3) -- not duplicated component-for-component since the
 * column set and data shape differ (submitter instead of club, no
 * open/closed variance to gate), but the same visual/interaction language.
 */
export function ClubSongsScreen({
  clubName,
  entries,
  loading,
  error,
  onOpenMix,
}: {
  clubName: string | null;
  entries: ClubSong[];
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
          songs{clubName ? ` · ${clubName}` : ""}
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
                id="club-songs-search"
                label="search"
                type="search"
                name="club-songs-search"
                autoComplete="off"
                placeholder="title or artist"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            {entries.length === 0 ? (
              <p className="mt-8 text-sm leading-[1.72] text-ink-muted">
                no songs yet -- they&apos;ll show up here once a mystery mix closes.
              </p>
            ) : visible.length === 0 ? (
              <p className="mt-8 text-sm leading-[1.72] text-ink-muted">
                no songs match &ldquo;{query}&rdquo;.
              </p>
            ) : (
              <ClubSongsGrid
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

function ClubSongsGrid({
  entries,
  sort,
  onSort,
  expanded,
  onToggle,
  onOpenMix,
}: {
  entries: ClubSong[];
  sort: SortKey;
  onSort: (sort: SortKey) => void;
  expanded: string | null;
  onToggle: (id: string) => void;
  onOpenMix: (mixId: string) => void;
}) {
  return (
    <div className="mt-6 overflow-hidden rounded-tile border border-hairline bg-card shadow-z2">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-foreground">
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
                    <td className="px-2 py-3 text-sm">{entry.submitter_display_name}</td>
                    <td className="px-2 py-3 font-mono text-mini text-muted-foreground">
                      {formatDate(entry.created_at)}
                    </td>
                    <td className="px-2 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.mix_number}
                    </td>
                    <td className="px-2 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.vote_count}
                    </td>
                    <td className="px-4 py-3 text-right font-mono text-mini text-muted-foreground">
                      {entry.notes.length}
                    </td>
                  </tr>
                  {open ? (
                    <tr className="border-b border-hairline-soft last:border-b-0">
                      <td colSpan={8} className="bg-tile px-4 py-4">
                        <ClubSongPreview entry={entry} onOpenMix={onOpenMix} />
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

/** The detail a grid cell can't hold: art, the mix's theme, the submitter's
 *  own note, who voted, and the notes thread. Voters/notes are always fully
 *  populated here -- every entry belongs to an already-closed mix, so there
 *  is no open-mix hidden case to render (unlike SubmissionHistoryScreen's
 *  preview). */
function ClubSongPreview({
  entry,
  onOpenMix,
}: {
  entry: ClubSong;
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
          <button
            type="button"
            onClick={() => onOpenMix(entry.mix_id)}
            className="font-mono uppercase tracking-mono text-label text-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-link"
          >
            open mix
          </button>
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

        {entry.voters.length > 0 ? (
          <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
            voted by{" "}
            {entry.voters
              .map((v) => (v.weight > 1 ? `${v.display_name} ×${v.weight}` : v.display_name))
              .join(", ")}
          </p>
        ) : null}

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
