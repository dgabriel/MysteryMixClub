import { useId, useState } from "react";
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
import { ConcentricRings } from "../ConcentricRings";
import { SourceBadge } from "../SourceBadge";
import { HelpLink } from "../HelpLink";

/**
 * SongSearchCard (MYS-45) — a permanent home-screen utility with two modes:
 *
 *  - "link":   paste a Spotify/YouTube URL → resolve to the canonical song
 *  - "search": search by title (+ optional artist) → pick a result → resolve
 *
 * Style guide: DM Serif Display heading, DM Mono everywhere else, underline-only
 * inputs (via TextField), the concentric-ring motif as the loader. This card is
 * intentionally Rust-free — the home screen spends its single Rust accent on the
 * My Clubs empty-state ring, so nothing here may compete for it.
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
const TOO_MANY = "Too many matches — try adding the artist name";

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
      <span className="font-mono uppercase tracking-label text-[9px] text-muted">{eyebrow}</span>
      <div className="mt-1 flex items-center gap-2">
        <h2 className="font-serif text-[20px] leading-tight text-ink">{heading}</h2>
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
                  onChange={(e) => setService(e.target.value as PasteSourceKey)}
                  disabled={loading}
                  className="mt-1 w-full border-b border-ink bg-transparent font-mono text-[13px] text-ink focus:border-sage focus:outline-none disabled:opacity-50"
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
      className="group flex w-full items-center gap-3 rounded-[2px] px-2 py-2 text-left transition-colors duration-150 hover:bg-sage-pale"
    >
      <Thumb url={track.thumbnail_url} alt={`${track.title} album art`} size={40} />
      <span className="min-w-0">
        <span className="block truncate font-mono text-[13px] text-ink">{track.title}</span>
        {track.artist ? (
          <span className="block truncate font-mono text-[11px] font-light text-muted group-hover:text-sage">
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
 * Spotify/Apple playlists — so we say so plainly before it's submitted. Sage Pale
 * panel, Default (Sage) source badge; no Rust — this is calm information, not the
 * screen's signal.
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
    <div className="mt-5 rounded-[3px] bg-sage-pale/60 px-6 py-5">
      <SourceBadge source={source} />
      <h3 className="mt-3 font-serif text-[18px] leading-tight text-ink">{song.title}</h3>
      {song.artist ? (
        <p className="mt-1 font-mono text-[11px] font-light text-sage">{song.artist}</p>
      ) : null}
      <p className="mt-4 font-mono text-[12px] font-light leading-relaxed text-ink">
        this one lives on {sourceLabel} only, so it won&apos;t be on the auto-generated Spotify or
        Apple Music playlists. everyone can still play it from its link.
      </p>
      <div className="mt-5 flex items-center gap-5">
        <Button type="button" onClick={onConfirm}>
          add it anyway
        </Button>
        <button
          type="button"
          onClick={onCancel}
          className="font-mono uppercase tracking-ui text-[11px] text-sage underline underline-offset-[3px] transition-colors duration-150 hover:text-ink"
        >
          search again
        </button>
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
      <div className="flex items-start gap-4">
        <Thumb url={song.thumbnail_url} alt={`${song.title} album art`} size={72} />
        <div className="min-w-0">
          <h3 className="truncate font-serif text-[18px] leading-tight text-ink">{song.title}</h3>
          {song.artist ? (
            <p className="mt-1 truncate font-mono text-[11px] font-light text-muted">
              {song.artist}
            </p>
          ) : null}
          {song.source ? (
            <span className="mt-2 inline-block">
              <SourceBadge source={song.source} />
            </span>
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
          <label
            htmlFor={noteId}
            className="block font-mono uppercase tracking-label text-[9px] text-muted"
          >
            leave a note (optional)
          </label>
          <textarea
            id={noteId}
            value={noteText ?? ""}
            onChange={(e) => onNoteChange(e.target.value)}
            maxLength={280}
            rows={2}
            disabled={submitting}
            placeholder="why this song?"
            className="mt-2 w-full resize-none border-b border-ink bg-transparent font-mono text-[12px] font-light text-ink placeholder:text-muted focus:border-ink focus:outline-none disabled:opacity-50"
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
