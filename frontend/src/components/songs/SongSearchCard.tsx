import { useId, useState, type ReactNode } from "react";
import {
  ApiError,
  resolveSong,
  searchSongs,
  type PlatformKey,
  type ResolvedSong,
  type SongSearchTrack,
} from "../../services/api";
import { Card } from "../Card";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { FormError } from "../FormError";
import { ConcentricRings } from "../ConcentricRings";
import { SourceBadge } from "../SourceBadge";
import { HelpLink } from "../HelpLink";

/**
 * SongSearchCard (MYS-45) — a permanent home-screen utility with two modes:
 *
 *  - "link":   paste a Spotify/YouTube URL → resolve to the canonical song
 *  - "search": search by title (+ optional artist) → pick a result → resolve
 *
 * Design System v1.0: a `Card` (Z1) surface, a `font-display` card title over a
 * mono eyebrow, mono labels, underline-only inputs via `TextField`, and the
 * record motif as the loader.
 *
 * **Where the amber goes.** Under the category rule the accent marks action or
 * achievement and nothing else, so here it marks only actions: the selected
 * mode tab, the primary CTA, and the `link`-variant text buttons. It never
 * touches a results row. A search returns up to ten rows, and an accent
 * repeated down a list stops being a signal and becomes the list's styling —
 * that is amber as pattern, which the rule forbids however in-category one row
 * would be. There is also no persistent selection to mark: clicking a row
 * resolves it immediately and replaces the whole list with the result view, so
 * a "selected row" state never exists to be accented. Rows are told apart by
 * their artwork and a `tile` hover fill instead.
 *
 * Album artwork gets the Z-Art treatment — see `Thumb`.
 */

type Mode = "link" | "search";
type ServiceKey = "spotify" | "youtube" | "appleMusic";
/** Sources a user can paste a link from. A superset of the preferred services:
 *  Bandcamp is a paste/link-out source only, never a preferred service. */
type PasteSourceKey = ServiceKey | "bandcamp";

const LINK_ERROR = "We couldn't find that song. Check the link and try again.";
const SEARCH_ERROR = "Something went wrong with that search. Try again.";
// A label using Bandcamp Pro's custom-domain feature redirects off
// bandcamp.com; we don't follow that redirect (MYS-200 SSRF guard), and
// MYS-212 tracks properly supporting it. The backend tags this specific
// case (see the "custom domain" substring check below) so we can give an
// accurate reason instead of the generic LINK_ERROR.
const BANDCAMP_CUSTOM_DOMAIN_ERROR =
  "Some Bandcamp Pro accounts with a custom domain aren't supported yet, but will be in the future. Try a link that stays on bandcamp.com.";

function isBandcampCustomDomainError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && err.message.includes("custom domain");
}
const TOO_MANY = "Too many matches. Try adding the artist name";

// Display order + labels for the platform link row. Keys match ResolvedSong.platforms.
const PLATFORMS: { key: PlatformKey; label: string }[] = [
  { key: "spotify", label: "Spotify" },
  { key: "appleMusic", label: "Apple Music" },
  { key: "deezer", label: "Deezer" },
  { key: "youtube", label: "YouTube" },
  { key: "youtubeMusic", label: "YouTube Music" },
  { key: "bandcamp", label: "Bandcamp" },
];

const SERVICES: { key: PasteSourceKey; label: string; placeholder: string }[] = [
  { key: "spotify", label: "Spotify", placeholder: "https://open.spotify.com/track/…" },
  { key: "youtube", label: "YouTube", placeholder: "https://www.youtube.com/watch?v=…" },
  { key: "appleMusic", label: "Apple Music", placeholder: "https://music.apple.com/…?i=…" },
  { key: "bandcamp", label: "Bandcamp", placeholder: "https://artist.bandcamp.com/track/…" },
];

// A source-only track (MYS-201) has a real track page on exactly one service
// family; every other platform's link is only a title/artist search that looks
// broken. Restrict the buttons to the platforms that are genuinely that track.
const SOURCE_PLATFORMS: Record<"youtube" | "bandcamp", PlatformKey[]> = {
  youtube: ["youtube", "youtubeMusic"],
  bandcamp: ["bandcamp"],
};

function serviceFromPref(pref: string | null | undefined): ServiceKey {
  if (pref === "youtube") return "youtube";
  if (pref === "appleMusic") return "appleMusic";
  return "spotify";
}

function detectService(url: string): PasteSourceKey | null {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host === "open.spotify.com") return "spotify";
    if (host === "music.apple.com") return "appleMusic";
    if (["youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"].includes(host))
      return "youtube";
    if (host === "bandcamp.com" || host.endsWith(".bandcamp.com")) return "bandcamp";
  } catch {
    // not a valid URL yet — ignore
  }
  return null;
}

/** Small line "open in new tab" glyph — 1.25px stroke, per the iconography spec. */
function ExternalLinkIcon() {
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
    >
      <path d="M6 3H3.5A1.5 1.5 0 0 0 2 4.5v8A1.5 1.5 0 0 0 3.5 14h8a1.5 1.5 0 0 0 1.5-1.5V10" />
      <path d="M10 2h4v4M14 2 7.5 8.5" />
    </svg>
  );
}

/** Loader: the rotating ring motif plus a screen-reader-only live announcement. */
function Loader({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center py-6">
      <ConcentricRings size={40} spinning />
      <span role="status" aria-live="polite" className="sr-only">
        {label}
      </span>
    </div>
  );
}

type SongSearchCardProps = {
  /** When provided, the resolved result card shows a submit affordance (e.g.
   *  "submit to this mix") that calls back with the resolved song. Returning
   *  false resets the card to the empty search state (used by duplicate-ISRC
   *  rejection — MYS-147). */
  onSubmit?: (song: ResolvedSong) => Promise<boolean> | boolean | void;
  submitting?: boolean;
  eyebrow?: string;
  heading?: ReactNode;
  /** Namespaces this card's input ids so several cards can share a screen
   *  without colliding ids (MYS-142 multi-slot submit). Defaults to "song" for
   *  the single-instance usages. */
  idPrefix?: string;
  /** Controlled note text — when provided, a textarea appears in the resolved
   *  view so the submitter can add context before submitting. */
  noteText?: string;
  onNoteChange?: (text: string) => void;
  /** User's preferred streaming service — seeds the link-tab service selector.
   *  Falls back to Spotify when absent or unrecognised (MYS-164). */
  preferredService?: string | null;
  /** When provided, shows a small "what is this?" icon beside the heading,
   *  linking to that /help section (MYS-222). Omit for contexts where the
   *  card isn't a real submission (e.g. the practice search on My Clubs) —
   *  a help link about submitting would be misleading there. */
  helpAnchor?: string;
};

export function SongSearchCard({
  onSubmit,
  submitting = false,
  eyebrow = "song search",
  heading = "find a song",
  idPrefix = "song",
  noteText,
  onNoteChange,
  preferredService,
  helpAnchor,
}: SongSearchCardProps = {}) {
  const [mode, setMode] = useState<Mode>("search");

  // link mode
  const [service, setService] = useState<PasteSourceKey>(() => serviceFromPref(preferredService));
  const [url, setUrl] = useState("");
  // search mode
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [results, setResults] = useState<SongSearchTrack[] | null>(null);
  const [tooMany, setTooMany] = useState(false);

  const [loading, setLoading] = useState(false);
  const [loadingLabel, setLoadingLabel] = useState("loading");
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState<ResolvedSong | null>(null);
  // A source-only match (MYS-201) awaiting the submitter's confirmation before it
  // becomes the resolved song — a Bandcamp/YouTube track that won't be on the
  // auto-generated Spotify/Apple playlists, so we say so first.
  const [pendingSourceOnly, setPendingSourceOnly] = useState<ResolvedSong | null>(null);

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setError(null);
    setResults(null);
    setTooMany(false);
    setResolved(null);
    setPendingSourceOnly(null);
  }

  function reset() {
    setUrl("");
    setTitle("");
    setArtist("");
    setResults(null);
    setTooMany(false);
    setError(null);
    setResolved(null);
    setPendingSourceOnly(null);
  }

  function handleUrlChange(next: string) {
    setUrl(next);
    const detected = detectService(next.trim());
    if (detected) setService(detected);
  }

  async function handleResolveLink(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setLoadingLabel("resolving song");
    setError(null);
    try {
      setResolved(await resolveSong({ url: trimmed }));
    } catch (err) {
      if (isBandcampCustomDomainError(err)) {
        // Same failure either way (the redirect guard raises before the
        // source-only funnel ever runs), so skip the pointless retry below.
        setError(BANDCAMP_CUSTOM_DOMAIN_ERROR);
        return;
      }
      // A source-only Bandcamp/YouTube track 404s by default (MYS-201). Only for
      // those two sources, retry opting in — if it resolves to a source-only
      // match, route it through the confirm step instead of the dead-end error.
      const detected = detectService(trimmed);
      if (
        err instanceof ApiError &&
        err.status === 404 &&
        (detected === "bandcamp" || detected === "youtube")
      ) {
        try {
          const song = await resolveSong({ url: trimmed, allow_source_only: true });
          if (song.source) {
            setPendingSourceOnly(song);
          } else {
            setResolved(song);
          }
        } catch {
          setError(LINK_ERROR);
        }
      } else {
        // Any other failure is the same calm, actionable message to the user.
        setError(LINK_ERROR);
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || loading) return;
    setLoading(true);
    setLoadingLabel("searching");
    setError(null);
    setResults(null);
    try {
      const res = await searchSongs(title, artist);
      setResults(res.results);
      setTooMany(res.too_many_results);
    } catch {
      setError(SEARCH_ERROR);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(track: SongSearchTrack) {
    if (loading) return;
    setLoading(true);
    setLoadingLabel("resolving song");
    setError(null);
    try {
      // Resolve by the picked track's identity — the server assembles the
      // cross-service links and echoes back the song fields.
      setResolved(
        await resolveSong({
          title: track.title,
          artist: track.artist,
          isrc: track.isrc,
          album: track.album,
          thumbnail_url: track.thumbnail_url,
        }),
      );
    } catch {
      setError(LINK_ERROR);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <span className="font-mono text-mini uppercase tracking-mono-caps text-muted-foreground">
        {eyebrow}
      </span>
      <div className="mt-2 flex items-center gap-2">
        <h2 className="font-display text-[1.375rem] font-bold uppercase leading-none tracking-display-snug">
          {heading}
        </h2>
        {helpAnchor ? <HelpLink anchor={helpAnchor} /> : null}
      </div>

      {pendingSourceOnly && pendingSourceOnly.source ? (
        <SourceOnlyConfirm
          song={pendingSourceOnly}
          source={pendingSourceOnly.source}
          onConfirm={() => {
            setResolved(pendingSourceOnly);
            setPendingSourceOnly(null);
          }}
          onCancel={reset}
        />
      ) : resolved ? (
        <ResultView
          song={resolved}
          onReset={reset}
          onSubmit={
            onSubmit
              ? async (song) => {
                  const ok = await Promise.resolve(onSubmit(song));
                  if (ok === false) reset();
                }
              : undefined
          }
          submitting={submitting}
          noteText={noteText}
          onNoteChange={onNoteChange}
        />
      ) : (
        <>
          {/* Mode toggle — search leads (the default), paste-a-link second. */}
          <div aria-label="search mode" className="mt-4 flex gap-6">
            <ModeTab active={mode === "search"} onClick={() => switchMode("search")}>
              search by title
            </ModeTab>
            <ModeTab active={mode === "link"} onClick={() => switchMode("link")}>
              paste a link
            </ModeTab>
          </div>

          {mode === "link" ? (
            <form onSubmit={handleResolveLink} noValidate className="mt-5">
              <div>
                <TextField
                  id={`${idPrefix}-link`}
                  label="paste a link"
                  placeholder={SERVICES.find((s) => s.key === service)?.placeholder ?? ""}
                  value={url}
                  onChange={(e) => handleUrlChange(e.target.value)}
                  disabled={loading}
                  inputMode="url"
                  autoComplete="off"
                  aria-invalid={error ? true : undefined}
                  aria-describedby={error ? `${idPrefix}-search-error` : undefined}
                />
                <p className="mt-2 text-meta leading-[1.6] text-muted-foreground">
                  paste any link and we'll detect the service automatically
                </p>
              </div>
              <div className="mt-5">
                <Button type="submit" disabled={loading || !url.trim()}>
                  resolve
                </Button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleSearch} noValidate className="mt-5 space-y-5">
              <TextField
                id={`${idPrefix}-title`}
                label="song title"
                placeholder="song title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={loading}
                autoComplete="off"
                required
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? `${idPrefix}-search-error` : undefined}
              />
              <TextField
                id={`${idPrefix}-artist`}
                label="artist (optional)"
                placeholder="artist"
                value={artist}
                onChange={(e) => setArtist(e.target.value)}
                disabled={loading}
                autoComplete="off"
              />
              <Button type="submit" disabled={loading || !title.trim()}>
                search
              </Button>
            </form>
          )}

          {loading ? <Loader label={loadingLabel} /> : null}

          {/* A failed resolve/search is a form-level validation message, so it
              takes the ADR 0004 treatment (destructive-text + warning icon) —
              its own color category, spending nothing from the accent. */}
          {error ? (
            <div className="mt-5">
              <FormError id={`${idPrefix}-search-error`}>{error}</FormError>
            </div>
          ) : null}

          {/* Search results */}
          {!loading && results !== null ? (
            <div className="mt-6">
              {tooMany ? (
                <p className="mb-3 text-meta leading-[1.6] text-muted-foreground">{TOO_MANY}</p>
              ) : null}
              {results.length === 0 ? (
                <p className="text-meta leading-[1.6] text-muted-foreground">no matches</p>
              ) : (
                <ul className="space-y-2">
                  {results.map((track) => (
                    <li key={track.id}>
                      <ResultRow track={track} onSelect={() => handleSelect(track)} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
}

function ModeTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={[
        "py-1.5 pb-1 font-mono uppercase tracking-mono text-label transition-colors duration-150",
        // Amber marks the selected tab — a selection is an interactive state,
        // and exactly one of the two tabs can hold it, so it never repeats.
        // The label carries the state too (`foreground` vs `muted-foreground`),
        // so the 1px rule is never the sole identifier (WCAG 1.4.11).
        active
          ? "border-b border-accent text-foreground"
          : "border-b border-transparent text-muted-foreground hover:text-foreground",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function ResultRow({ track, onSelect }: { track: SongSearchTrack; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className="group flex w-full items-center gap-4 rounded-tile px-2 py-2 text-left transition-colors duration-150 hover:bg-tile"
    >
      <Thumb url={track.thumbnail_url} alt={`${track.title} album art`} size={40} interactive />
      <span className="min-w-0">
        <span
          className="block truncate font-display text-sm font-semibold uppercase leading-none"
          title={track.title}
        >
          {track.title}
        </span>
        {track.artist ? (
          <span className="mt-1.5 block truncate font-mono text-mini text-muted-foreground transition-colors duration-150 group-hover:text-foreground">
            {track.artist}
          </span>
        ) : null}
      </span>
    </button>
  );
}

/**
 * Confirmation step for a source-only pick (MYS-201). A Bandcamp/YouTube track
 * with no catalog ISRC resolved, but it won't land on the auto-generated
 * Spotify/Apple playlists — so we say so plainly before it's submitted.
 *
 * The well is `sunken`, not `panel` or `tile`. A brand-tinted `SourceBadge` is
 * read against its own ~6% tint composited over whatever is beneath it, and it
 * is AA-safe on `floor`/`sunken`/`card`/`popover` only — YouTube red falls to
 * 4.22:1 on `tile` and worse above (see the table in `lib/platformBrand.ts`).
 * `sunken` is the one inset surface that satisfies that and still separates the
 * callout from the `card` around it, so this is a well rather than a raised
 * panel. It measures 4.91:1 for YouTube and 6.24:1 for Bandcamp.
 *
 * The copy is calm information; the accent sits on the two actions only.
 */
function SourceOnlyConfirm({
  song,
  source,
  onConfirm,
  onCancel,
}: {
  song: ResolvedSong;
  source: "youtube" | "bandcamp";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const sourceLabel = source === "bandcamp" ? "Bandcamp" : "YouTube";
  return (
    <div className="mt-5 rounded-tile border border-hairline bg-sunken px-6 py-5">
      <SourceBadge source={source} />
      <h3 className="mt-4 font-display text-sm font-semibold uppercase leading-none">
        {song.title}
      </h3>
      {song.artist ? (
        <p className="mt-2 font-mono text-mini text-muted-foreground">{song.artist}</p>
      ) : null}
      <p className="mt-4 text-sm leading-[1.65] text-foreground">
        this one lives on {sourceLabel} only, so it won&apos;t be on the auto-generated Spotify or
        Apple Music playlists. everyone can still play it from its link.
      </p>
      <div className="mt-6 flex items-center gap-6">
        <Button type="button" onClick={onConfirm}>
          add it anyway
        </Button>
        <Button variant="link" type="button" onClick={onCancel}>
          search again
        </Button>
      </div>
    </div>
  );
}

function ResultView({
  song,
  onReset,
  onSubmit,
  submitting,
  noteText,
  onNoteChange,
}: {
  song: ResolvedSong;
  onReset: () => void;
  onSubmit?: (song: ResolvedSong) => void;
  submitting?: boolean;
  noteText?: string;
  onNoteChange?: (text: string) => void;
}) {
  const available = PLATFORMS.filter((p) => {
    if (!song.platforms[p.key]) return false;
    if (song.source) return SOURCE_PLATFORMS[song.source].includes(p.key);
    return true;
  });
  const noteId = useId();
  return (
    <div className="mt-5">
      <div className="flex items-start gap-6">
        <Thumb url={song.thumbnail_url} alt={`${song.title} album art`} size={72} />
        <div className="min-w-0">
          <h3
            className="truncate font-display text-sm font-semibold uppercase leading-none"
            title={song.title}
          >
            {song.title}
          </h3>
          {song.artist ? (
            <p className="mt-2 truncate font-mono text-mini text-muted-foreground">{song.artist}</p>
          ) : null}
          {/* The badge sits directly on the Card's `card` surface — 4.74:1 for
              YouTube, 5.98:1 for Bandcamp. Nothing lighter may go under it. */}
          {song.source ? (
            <span className="mt-2 inline-block">
              <SourceBadge source={song.source} />
            </span>
          ) : null}
          {song.album ? (
            <p className="mt-1 truncate font-mono text-mini text-muted-foreground">{song.album}</p>
          ) : null}
        </div>
      </div>

      {available.length > 0 ? (
        <div className="mt-6">
          <span className="block font-mono text-mini uppercase tracking-mono-caps text-muted-foreground">
            listen on
          </span>
          <ul className="mt-4 flex flex-wrap gap-2">
            {available.map((p) => (
              <li key={p.key}>
                {/* The ghost-button treatment as an anchor: a `tile` fill, not a
                    bare hairline box, so the control is identifiable without
                    relying on a ~1.1:1 edge. */}
                <a
                  href={song.platforms[p.key]}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`open ${song.title} on ${p.label} (opens in a new tab)`}
                  className="inline-flex items-center gap-2 rounded-hair border border-hairline bg-tile px-3 py-2 font-mono uppercase tracking-mono text-label text-foreground transition-colors duration-150 hover:bg-panel"
                >
                  <ExternalLinkIcon />
                  {p.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-6 text-meta leading-[1.6] text-muted-foreground">
          no streaming links available for this song
        </p>
      )}

      {onNoteChange !== undefined ? (
        <div className="mt-6">
          <label
            htmlFor={noteId}
            className="block font-mono text-mini uppercase tracking-mono-caps text-muted-foreground"
          >
            leave a note (optional)
          </label>
          {/* Same underline-only treatment as TextField, including its resting
              `muted-foreground` rule (a hairline underline would be the sole
              affordance at ~1.2:1). Disabled drops the value to
              `muted-foreground` rather than fading the field out. */}
          <textarea
            id={noteId}
            value={noteText ?? ""}
            onChange={(e) => onNoteChange(e.target.value)}
            maxLength={280}
            rows={2}
            disabled={submitting}
            placeholder="why this song?"
            className="mt-2 w-full resize-none rounded-none border-0 border-b border-muted-foreground bg-transparent px-0 py-1 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:text-muted-foreground"
          />
        </div>
      ) : null}

      <div className="mt-6 flex items-center gap-6">
        {onSubmit ? (
          <Button type="button" onClick={() => onSubmit(song)} disabled={submitting}>
            {submitting ? "submitting…" : "submit this song"}
          </Button>
        ) : null}
        <Button variant="link" type="button" onClick={onReset} disabled={submitting}>
          search again
        </Button>
      </div>
    </div>
  );
}

/**
 * Album artwork at Z-Art — the one class of object that sits above the Z4
 * ceiling of the surface ladder. A same-size `panel` block is laid down first
 * and the image floats over it, offset up and to the left, so the art reads as
 * a physical object resting on the card rather than as a picture printed into
 * it. The block is what shows through while the image is still loading, and it
 * is the entire treatment when there is no art: `thumbnail_url` is the only art
 * field either `ResolvedSong` or `SongSearchTrack` carries (neither has
 * `album_art_url`, which belongs to the submission types), and it is nullable
 * on both — a null `src` would render a broken image, so the null case renders
 * the placeholder and nothing else.
 *
 * The 1px white ring lives inside `shadow-z4` / `shadow-art`, so the art
 * deliberately carries no `border`. Artwork inside an interactive row rests at
 * `shadow-z4` and rises to `shadow-art` on that row's hover; the resolved
 * view's art is not interactive, so it wears `shadow-art` at rest as the hero
 * object of that view instead of advertising a hover that does nothing (the
 * same reasoning `Card` uses for having no hover elevation of its own).
 *
 * The offset only works if nothing clips it. Neither `Card` nor any wrapper on
 * the path sets `overflow-hidden`, and both offsets stay inside their
 * container's own padding, so the art overlaps padding rather than escaping the
 * card.
 */
function Thumb({
  url,
  alt,
  size,
  interactive = false,
}: {
  url: string | null;
  alt: string;
  size: number;
  /** Art inside a hoverable row: rest at `shadow-z4`, rise to `shadow-art`.
   *  Requires a `group` on the hover target. */
  interactive?: boolean;
}) {
  // 4px on a 40px row thumb, 6px on the 72px resolved-view art — both inside
  // the 4-12px the treatment calls for, and inside their container's padding.
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
          className={[
            "absolute rounded-hair object-cover transition-shadow duration-150",
            interactive ? "shadow-z4 group-hover:shadow-art" : "shadow-art",
          ].join(" ")}
          style={{ width: size, height: size, top: -offset, left: -offset }}
        />
      ) : null}
    </span>
  );
}
