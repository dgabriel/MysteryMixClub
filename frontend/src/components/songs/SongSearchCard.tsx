import { useState } from "react";
import {
  resolveSong,
  searchSongs,
  type PlatformKey,
  type ResolvedSong,
  type SongSearchTrack,
} from "../../services/api";
import { Card } from "../Card";
import { Button } from "../Button";
import { TextField } from "../TextField";
import { ConcentricRings } from "../ConcentricRings";

/**
 * SongSearchCard (MYS-45) — a permanent home-screen utility with two modes:
 *
 *  - "link":   paste a Spotify/YouTube URL → resolve to the canonical song
 *  - "search": search by title (+ optional artist) → pick a result → resolve
 *
 * Style guide: DM Serif Display heading, DM Mono everywhere else, underline-only
 * inputs (via TextField), the concentric-ring motif as the loader. This card is
 * intentionally Rust-free — the home screen spends its single Rust accent on the
 * My Leagues empty-state ring, so nothing here may compete for it.
 */

type Mode = "link" | "search";
type ServiceKey = "spotify" | "youtube" | "appleMusic";

const LINK_ERROR = "We couldn't find that song. Check the link and try again.";
const SEARCH_ERROR = "Something went wrong with that search. Try again.";
const TOO_MANY = "Too many matches — try adding the artist name";

// Display order + labels for the platform link row. Keys match ResolvedSong.platforms.
const PLATFORMS: { key: PlatformKey; label: string }[] = [
  { key: "spotify", label: "Spotify" },
  { key: "appleMusic", label: "Apple Music" },
  { key: "deezer", label: "Deezer" },
  { key: "youtube", label: "YouTube" },
];

const SERVICES: { key: ServiceKey; label: string; placeholder: string }[] = [
  { key: "spotify", label: "Spotify", placeholder: "https://open.spotify.com/track/…" },
  { key: "youtube", label: "YouTube", placeholder: "https://www.youtube.com/watch?v=…" },
  { key: "appleMusic", label: "Apple Music", placeholder: "https://music.apple.com/…?i=…" },
];

function serviceFromPref(pref: string | null | undefined): ServiceKey {
  if (pref === "youtube") return "youtube";
  if (pref === "appleMusic") return "appleMusic";
  return "spotify";
}

function detectService(url: string): ServiceKey | null {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host === "open.spotify.com") return "spotify";
    if (host === "music.apple.com") return "appleMusic";
    if (["youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"].includes(host))
      return "youtube";
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
   *  "submit to this round") that calls back with the resolved song. Returning
   *  false resets the card to the empty search state (used by duplicate-ISRC
   *  rejection — MYS-147). */
  onSubmit?: (song: ResolvedSong) => Promise<boolean> | boolean | void;
  submitting?: boolean;
  eyebrow?: string;
  heading?: string;
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
}: SongSearchCardProps = {}) {
  const [mode, setMode] = useState<Mode>("search");

  // link mode
  const [service, setService] = useState<ServiceKey>(() => serviceFromPref(preferredService));
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

  function switchMode(next: Mode) {
    if (next === mode) return;
    setMode(next);
    setError(null);
    setResults(null);
    setTooMany(false);
    setResolved(null);
  }

  function reset() {
    setUrl("");
    setTitle("");
    setArtist("");
    setResults(null);
    setTooMany(false);
    setError(null);
    setResolved(null);
  }

  function handleUrlChange(next: string) {
    setUrl(next);
    const detected = detectService(next.trim());
    if (detected) setService(detected);
  }

  async function handleResolveLink(event: React.FormEvent) {
    event.preventDefault();
    if (!url.trim() || loading) return;
    setLoading(true);
    setLoadingLabel("resolving song");
    setError(null);
    try {
      setResolved(await resolveSong({ url: url.trim() }));
    } catch {
      // Any failure here is the same calm, actionable message to the user.
      setError(LINK_ERROR);
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
      <span className="font-mono uppercase tracking-label text-[9px] text-muted">{eyebrow}</span>
      <h2 className="mt-1 font-serif text-[20px] leading-tight text-ink">{heading}</h2>

      {resolved ? (
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
          <div role="tablist" aria-label="search mode" className="mt-4 flex gap-6">
            <ModeTab active={mode === "search"} onClick={() => switchMode("search")}>
              search by title
            </ModeTab>
            <ModeTab active={mode === "link"} onClick={() => switchMode("link")}>
              paste a link
            </ModeTab>
          </div>

          {mode === "link" ? (
            <form onSubmit={handleResolveLink} className="mt-5">
              <div>
                <label
                  htmlFor={`${idPrefix}-service`}
                  className="block font-mono uppercase tracking-label text-[9px] text-muted"
                >
                  service
                </label>
                <select
                  id={`${idPrefix}-service`}
                  value={service}
                  onChange={(e) => setService(e.target.value as ServiceKey)}
                  disabled={loading}
                  className="mt-1 w-full border-b border-border bg-transparent font-mono text-[13px] text-ink focus:border-sage focus:outline-none disabled:opacity-50"
                >
                  {SERVICES.map((s) => (
                    <option key={s.key} value={s.key}>
                      {s.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="mt-5">
                <TextField
                  id={`${idPrefix}-link`}
                  label="paste a link"
                  placeholder={SERVICES.find((s) => s.key === service)?.placeholder ?? ""}
                  value={url}
                  onChange={(e) => handleUrlChange(e.target.value)}
                  disabled={loading}
                  inputMode="url"
                  autoComplete="off"
                />
                <p className="mt-2 font-mono text-[11px] font-light text-muted">
                  paste any link — we'll detect the service automatically
                </p>
              </div>
              <div className="mt-5">
                <Button type="submit" disabled={loading || !url.trim()}>
                  resolve
                </Button>
              </div>
            </form>
          ) : (
            <form onSubmit={handleSearch} className="mt-5 space-y-5">
              <TextField
                id={`${idPrefix}-title`}
                label="song title"
                placeholder="song title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={loading}
                autoComplete="off"
                required
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

          {error ? (
            <p role="alert" className="mt-5 font-mono text-[11px] font-light text-ink">
              {error}
            </p>
          ) : null}

          {/* Search results */}
          {!loading && results !== null ? (
            <div className="mt-6">
              {tooMany ? (
                <p className="mb-3 font-mono text-[11px] font-light text-muted">{TOO_MANY}</p>
              ) : null}
              {results.length === 0 ? (
                <p className="font-mono text-[11px] font-light text-muted">no matches</p>
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
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={[
        "font-mono uppercase tracking-ui text-[11px] pb-1 transition-colors duration-150",
        active
          ? "text-ink border-b border-sage"
          : "text-muted border-b border-transparent hover:text-ink",
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
      className="flex w-full items-center gap-3 rounded-[2px] px-2 py-2 text-left transition-colors duration-150 hover:bg-sage-pale"
    >
      <Thumb url={track.thumbnail_url} alt={`${track.title} album art`} size={40} />
      <span className="min-w-0">
        <span className="block truncate font-mono text-[13px] text-ink">{track.title}</span>
        {track.artist ? (
          <span className="block truncate font-mono text-[11px] font-light text-muted">
            {track.artist}
          </span>
        ) : null}
      </span>
    </button>
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
  const available = PLATFORMS.filter((p) => song.platforms[p.key]);
  return (
    <div className="mt-5">
      <div className="flex items-start gap-4">
        <Thumb url={song.thumbnail_url} alt={`${song.title} album art`} size={72} />
        <div className="min-w-0">
          <h3 className="truncate font-serif text-[18px] leading-tight text-ink">{song.title}</h3>
          {song.artist ? (
            <p className="mt-1 truncate font-mono text-[11px] font-light text-muted">
              {song.artist}
            </p>
          ) : null}
          {song.album ? (
            <p className="mt-0.5 truncate font-mono text-[11px] font-light text-muted">
              {song.album}
            </p>
          ) : null}
        </div>
      </div>

      {available.length > 0 ? (
        <div className="mt-5">
          <span className="block font-mono uppercase tracking-label text-[9px] text-muted">
            listen on
          </span>
          <ul className="mt-3 flex flex-wrap gap-2">
            {available.map((p) => (
              <li key={p.key}>
                <a
                  href={song.platforms[p.key]}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`open ${song.title} on ${p.label} (opens in a new tab)`}
                  className="inline-flex items-center gap-1.5 rounded-[2px] border border-border px-2.5 py-1 font-mono uppercase tracking-ui text-[11px] text-ink transition-colors duration-150 hover:bg-sage-pale"
                >
                  <ExternalLinkIcon />
                  {p.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-5 font-mono text-[11px] font-light text-muted">
          no streaming links available for this song
        </p>
      )}

      {onNoteChange !== undefined ? (
        <div className="mt-5">
          <label className="block font-mono uppercase tracking-label text-[9px] text-muted">
            leave a note (optional)
          </label>
          <textarea
            value={noteText ?? ""}
            onChange={(e) => onNoteChange(e.target.value)}
            maxLength={280}
            rows={2}
            disabled={submitting}
            placeholder="why this song?"
            className="mt-2 w-full resize-none border-b border-border bg-transparent font-mono text-[12px] font-light text-ink placeholder:text-muted focus:border-ink focus:outline-none disabled:opacity-50"
          />
        </div>
      ) : null}

      <div className="mt-6 flex items-center gap-5">
        {onSubmit ? (
          <Button type="button" onClick={() => onSubmit(song)} disabled={submitting}>
            {submitting ? "submitting…" : "submit this song"}
          </Button>
        ) : null}
        <button
          type="button"
          onClick={onReset}
          disabled={submitting}
          className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink disabled:opacity-50"
        >
          search again
        </button>
      </div>
    </div>
  );
}

/** Album-art thumbnail with a ring-motif fallback when no art is available. */
function Thumb({ url, alt, size }: { url: string | null; alt: string; size: number }) {
  if (url) {
    return (
      <img
        src={url}
        alt={alt}
        width={size}
        height={size}
        className="flex-shrink-0 rounded-[2px] object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  return (
    <span
      className="flex flex-shrink-0 items-center justify-center rounded-[2px] bg-sage-pale"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <ConcentricRings size={Math.round(size * 0.6)} />
    </span>
  );
}
