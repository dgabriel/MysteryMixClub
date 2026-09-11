import { useMemo, useState } from "react";
import type { MySubmission } from "../services/api";
import { PaperSurface } from "../components/PaperSurface";
import { TextField } from "../components/TextField";
import { Card } from "../components/Card";
import { Badge } from "../components/Badge";
import { ClubName } from "../components/ClubName";
import { SourceBadge } from "../components/SourceBadge";
import { ConcentricRings } from "../components/ConcentricRings";
import { MIX_BADGE, MIX_STATE_LABEL, mixGroup } from "../utils/mixState";

type SortKey = "newest" | "title" | "artist" | "club";

const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "newest", label: "newest" },
  { key: "title", label: "title" },
  { key: "artist", label: "artist" },
  { key: "club", label: "club" },
];

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

/**
 * Every song the caller has ever submitted, across every club
 * (MysteryMixClub-ps1w.1) -- searchable by title/artist, sortable by newest,
 * title, artist, or club. Filtering/sorting happen client-side over the one
 * list `GET /users/me/submissions` returns, the same way ProfileRoute already
 * treats archived clubs -- there's no pagination convention elsewhere in this
 * app, and its invite-only, friend-group scale doesn't call for one here.
 *
 * Renders on the light `paper` surface (ADR 0013) with dark `Card` islands for
 * each submission, mirroring the mix screen's closed-mix reveal ("the picks"
 * list) since this is largely the same data reshaped across clubs.
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
      <main className="mx-auto w-full max-w-2xl px-4 pt-8 pb-16 sm:px-8">
        <h1 className="font-display text-[1.75rem] font-extrabold uppercase leading-[0.9] tracking-display-snug text-ink">
          my submissions
        </h1>

        {error ? (
          <p role="alert" className="mt-6 text-sm leading-[1.72] text-ink">
            {error}
          </p>
        ) : (
          <>
            <div className="mt-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
              <div className="min-w-0 flex-1">
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
              {/* Segmented sort control -- same "exactly one selected, permanent
                  furniture" treatment as AdminScreen's waitlist status filter. */}
              <div className="flex gap-4 pb-[10px]">
                {SORT_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setSort(option.key)}
                    aria-pressed={sort === option.key}
                    className={[
                      "py-1.5 font-mono uppercase tracking-mono text-mini transition-colors duration-150",
                      sort === option.key
                        ? "text-ink underline underline-offset-[3px]"
                        : "text-ink-muted hover:text-ink-accent",
                    ].join(" ")}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
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
              <ul className="mt-6 space-y-4">
                {visible.map((entry) => (
                  <li key={entry.submission_id}>
                    <SubmissionCard entry={entry} onOpenMix={onOpenMix} />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </main>
    </PaperSurface>
  );
}

/** Z-Art album thumbnail, matching the mix screen's reveal treatment
 *  (`MixDetailRoute`'s `AlbumArt` / `SongSearchCard`'s `Thumb`). Not shared
 *  from either -- both are file-private, and hoisting a common primitive is
 *  MysteryMixClub-jz3y's scope, not this ticket's. */
function AlbumArt({ url, alt, size = 56 }: { url: string | null; alt: string; size?: number }) {
  const offset = size >= 64 ? 6 : 4;
  return (
    <span className="relative block shrink-0" style={{ width: size, height: size }}>
      <span aria-hidden="true" className="block h-full w-full rounded-hair bg-panel" />
      {url ? (
        <img
          src={url}
          alt={alt}
          width={size}
          height={size}
          className="absolute rounded-hair object-cover shadow-art"
          style={{ width: size, height: size, top: -offset, left: -offset }}
        />
      ) : null}
    </span>
  );
}

/** Notes list + disclosure, matching the mix screen reveal's `CollapsibleNotes`
 *  (same duplication note as `AlbumArt` above). Collapsed by default so a long
 *  thread doesn't bury the list. */
function CollapsibleNotes({ notes }: { notes: MySubmission["notes"] }) {
  const [open, setOpen] = useState(false);
  const label = `${notes.length} ${notes.length === 1 ? "note" : "notes"}`;
  return (
    <div className="mt-3 border-t border-hairline-soft pt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="font-mono uppercase tracking-mono text-label text-muted-foreground underline underline-offset-[3px] transition-colors duration-150 hover:text-foreground"
      >
        {open ? `hide ${label}` : `show ${label}`}
      </button>
      {open ? (
        <ul className="mt-3 space-y-3">
          {notes.map((note, i) => (
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
  );
}

function SubmissionCard({
  entry,
  onOpenMix,
}: {
  entry: MySubmission;
  onOpenMix: (mixId: string) => void;
}) {
  return (
    <Card className="transition-[box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:shadow-z3">
      {/* Whole-row click-to-navigate, matching ClubHomeScreen's mix row: the
          notes disclosure below is a SIBLING after this button closes, never
          nested inside it -- a clickable descendant inside a clickable
          ancestor is both invalid HTML and a real bug (the toggle's click
          would bubble and navigate away at the same time). */}
      <button
        type="button"
        onClick={() => onOpenMix(entry.mix_id)}
        className="block w-full text-left"
      >
        <div className="flex items-start gap-4">
          <AlbumArt url={entry.album_art_url} alt={`${entry.title} album art`} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
              <span className="font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                <ClubName name={entry.club_name} /> · mix {entry.mix_number}
                {entry.theme ? ` · ${entry.theme}` : ""}
              </span>
              <Badge variant={MIX_BADGE[mixGroup(entry.state)]}>{MIX_STATE_LABEL[entry.state]}</Badge>
            </div>
            <h3 className="mt-2 font-display text-sm font-bold uppercase leading-none">
              {entry.title}
            </h3>
            <p className="mt-2 font-mono text-mini text-muted-foreground">{entry.artist}</p>
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
              <>
                <p className="mt-2 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                  {entry.vote_count} {entry.vote_count === 1 ? "vote" : "votes"}
                </p>
                {entry.voters.length > 0 ? (
                  <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
                    voted by{" "}
                    {entry.voters
                      .map((v) =>
                        v.weight > 1 ? `${v.display_name} ×${v.weight}` : v.display_name,
                      )
                      .join(", ")}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="mt-2 font-mono uppercase tracking-mono-caps text-mini text-muted-foreground">
                votes reveal once this mix closes
              </p>
            )}
          </div>
        </div>
      </button>
      {entry.notes.length > 0 ? <CollapsibleNotes notes={entry.notes} /> : null}
    </Card>
  );
}
