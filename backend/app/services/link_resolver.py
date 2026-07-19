"""Keyless paste-a-link resolver (MYS-81).

Replaces the retired Odesli public API for the *paste a link* path of
``POST /api/v1/songs/resolve``. Given a pasted platform URL, it returns a small
song identity (title/artist/isrc/album/thumbnail). Cross-service playback links
are assembled separately by :mod:`app.services.song_links`, exactly as before —
this module only identifies the song.

The linchpin: a submission REQUIRES an ISRC, and only Deezer returns one
keyless. So every path funnels through Deezer:

* Deezer  (``deezer.com/.../track/{id}``) — direct ``GET /track/{id}`` gives
  title/artist/isrc/album/cover. Exact, no search needed.
* Apple   (``music.apple.com`` with ``?i={trackId}``) — iTunes lookup gives
  trackName + artistName (no ISRC) → Deezer-search for the canonical identity.
* Spotify (``open.spotify.com/track/{id}``) — oEmbed gives the track title only
  (no artist) → Deezer-search the title. Weakest path; expected.
* YouTube (``youtube.com/watch``, ``youtu.be``, ``music.youtube.com``) — oEmbed
  gives a noisy "Artist - Title (Official Video)" string + author → cleaned →
  Deezer-search.
* Bandcamp (``{artist}.bandcamp.com/track/{slug}``) — no oEmbed and no public
  API, but track pages carry OpenGraph meta: ``og:title`` is reliably
  "Track Title, by Artist Name" → split → Deezer-search.

``ResolvedSong`` (the endpoint's response model, including assembled platform
links) also lives here now that Odesli is gone; the resolver itself returns the
leaner :class:`SongIdentity`.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx
from pydantic import BaseModel

from app.services.deezer_search import (
    DeezerError,
    DeezerRateLimitError,
    DeezerSearchClient,
    DeezerTimeoutError,
    DeezerUnavailableError,
    build_deezer_client,
)
from app.services.spotify_client import SpotifyClient, get_spotify_client

_DEEZER_TRACK = "https://api.deezer.com/track/{id}"
_ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
_SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
_YOUTUBE_OEMBED = "https://www.youtube.com/oembed"
_DEFAULT_TIMEOUT = 10.0


class ResolvedSong(BaseModel):
    """Normalized, platform-agnostic song identity returned to callers.

    Kept stable across the Odesli -> keyless migration (MYS-81) so the API
    contract and the frontend are unchanged.
    """

    title: str
    artist: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None
    isrc: str | None = None
    # Only platforms that actually have a link for this song are present.
    # Keys are a subset of {"spotify", "appleMusic", "deezer", "youtube",
    # "youtubeMusic", "bandcamp"}.
    platforms: dict[str, str]


class SongIdentity(BaseModel):
    """Bare song identity produced by the resolver (no platform links)."""

    title: str
    artist: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None
    isrc: str | None = None


# --------------------------------------------------------------------------- #
# Errors — a resolver-agnostic hierarchy the router maps to HTTP status codes.
# Callers catch these, never httpx exceptions, so the upstreams stay sealed.
# --------------------------------------------------------------------------- #
class ResolverError(Exception):
    """Base class for all paste-a-link resolution failures."""


class InvalidSongURLError(ResolverError):
    """The supplied URL is malformed or not a resolvable music link (-> 400)."""


class SongNotFoundError(ResolverError):
    """The URL could not be matched to a song (-> 404)."""


class ResolverRateLimitError(ResolverError):
    """An upstream returned a rate limit (-> 429)."""


class ResolverTimeoutError(ResolverError):
    """A request to an upstream timed out (-> 504)."""


class ResolverUnavailableError(ResolverError):
    """An upstream returned an unexpected error or was unreachable (-> 502)."""


def _looks_like_url(value: str) -> bool:
    candidate = value.strip().lower()
    return candidate.startswith("http://") or candidate.startswith("https://")


# Bandcamp page fetch hardening (server-side fetch of a user-supplied URL):
# redirects are followed manually, only within the Bandcamp host family, and
# capped; the body read is capped because og:title always sits in <head>.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECT_HOPS = 3
_MAX_PAGE_BYTES = 1 << 20  # 1 MiB


def _is_bandcamp_host(host: str) -> bool:
    return host == "bandcamp.com" or host.endswith(".bandcamp.com")


def _bandcamp_redirect_target(current: str, location: str | None) -> str:
    """Absolute redirect target, validated to stay on the Bandcamp host family.

    Custom artist domains are out of scope (MYS-200), so an off-family (or
    missing/non-http) target is treated as an unsupported link — the same
    :class:`SongNotFoundError` the user would get pasting it directly. Blindly
    following would let a hostile redirect aim this server-side fetch at
    internal targets (SSRF)."""
    if not location:
        raise SongNotFoundError("could not resolve that link")
    target = urljoin(current, location)
    host = (urlparse(target).hostname or "").lower()
    if not _looks_like_url(target) or not _is_bandcamp_host(host):
        raise SongNotFoundError("could not resolve that link")
    return target


# Trailing decorations to strip from a title before a Deezer search: a bracketed
# group ("(Official Video)", "(Full Length Version)", "(Remastered 2022)", "[HD]")
# that YouTube uploaders and the iTunes catalog append, or a trailing "| ..."
# segment. Stripped repeatedly because they stack (e.g. "(Audio) (HD)").
_TITLE_NOISE = re.compile(r"\s*(?:[\(\[][^)\]]*[\)\]]|\|.*)\s*$")


def _clean_title(title: str) -> str:
    """Strip trailing bracket/pipe decorations so a noisy store/upload title
    matches a canonical track (e.g. "American Pie (Full Length Version)" ->
    "American Pie", "Song - Title (Lyric Video)" -> "Song - Title")."""
    cleaned = title.strip()
    while True:
        stripped = _TITLE_NOISE.sub("", cleaned).strip()
        if stripped == cleaned or not stripped:
            break
        cleaned = stripped
    return cleaned or title.strip()


# OpenGraph title extraction, in two steps so the content capture can never
# cross a tag boundary: first isolate the og:title ``<meta>`` tag as a unit
# (``[^>]*`` keeps the match inside one tag, in either attribute order), then
# pull ``content`` out of that tag alone. A one-shot regex with the property
# check *after* a free content capture would instead latch onto an earlier
# meta's ``content=`` (og:site_name, og:type — every real Bandcamp page) and
# swallow across tags. Tradeoff of ``[^>]*``: a literal unescaped ``>`` inside
# a quoted attribute value would break the tag match — acceptable, since
# server-rendered og tags entity-escape those.
# The (?<![\w-]) lookbehinds keep hyphenated attributes like data-property= or
# data-content= from matching (a plain \b would let them through).
_OG_TITLE_META = re.compile(
    r"""<meta\b[^>]*(?<![\w-])property=(["'])og:title\1[^>]*>""",
    re.IGNORECASE,
)
# The quote around ``content`` is captured and backreferenced so a title
# containing the *other* quote character (e.g. an apostrophe inside double
# quotes) doesn't truncate the match.
_META_CONTENT = re.compile(
    r"""(?<![\w-])content=(["'])(?P<content>.*?)\1""",
    re.IGNORECASE,
)


def _og_title(page: str) -> str | None:
    """Extract a page's ``og:title`` meta content, unescaped, or None."""
    tag = _OG_TITLE_META.search(page)
    if not tag:
        return None
    match = _META_CONTENT.search(tag.group(0))
    if not match:
        return None
    content = html.unescape(match.group("content")).strip()
    return content or None


def _topic_artist(author: str | None) -> str | None:
    """Artist behind a YouTube Music auto-generated "Artist - Topic" channel,
    else None. Other channel names (e.g. "DonMcLeanVEVO") are unreliable artist
    hints, so we don't guess from them."""
    if not author:
        return None
    text = author.strip()
    if text.lower().endswith("- topic"):
        return text[: -len("- topic")].rstrip(" -").strip() or None
    return None


class LinkResolver:
    """Identifies the song behind a pasted platform URL, keyless.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a
    mock transport; in production it defaults to a real client with a timeout.
    The same factory backs the internal Deezer search funnel so tests stay
    fully offline.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        deezer: DeezerSearchClient | None = None,
        spotify: SpotifyClient | None = None,
    ) -> None:
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        # Reuse the keyless Deezer search for the apple/spotify/youtube funnel.
        self._deezer = deezer or DeezerSearchClient(
            timeout=timeout, client_factory=self._client_factory
        )
        # Optional: when Spotify is configured, resolve Spotify track ids exactly
        # via its API instead of the lossy oEmbed-title -> Deezer-search path.
        self._spotify = spotify

    # ----------------------------------------------------------------- #
    # HTTP helper — maps httpx/status failures onto the resolver hierarchy.
    # ----------------------------------------------------------------- #
    async def _get_json(self, url: str, params: dict | None = None) -> dict:
        try:
            async with self._client_factory() as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ResolverTimeoutError("song lookup timed out") from exc
        except httpx.HTTPError as exc:
            raise ResolverUnavailableError("could not reach upstream") from exc

        if response.status_code == 429:
            raise ResolverRateLimitError("upstream rate limit exceeded")
        if response.status_code in (400, 404):
            raise SongNotFoundError("could not resolve that link")
        if response.status_code >= 500:
            raise ResolverUnavailableError(f"upstream returned {response.status_code}")
        if response.status_code != 200:
            raise ResolverUnavailableError(f"unexpected upstream status {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ResolverUnavailableError("upstream returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise SongNotFoundError("unexpected upstream response shape")
        return payload

    async def _get_text(self, url: str) -> str:
        """Like :meth:`_get_json`, for HTML pages, hardened for a server-side
        fetch of a user-supplied URL:

        * Redirects (Bandcamp artist pages occasionally 301) are followed
          manually — only within the Bandcamp host family, capped at
          ``_MAX_REDIRECT_HOPS`` — instead of ``follow_redirects=True``, which
          would follow a hostile redirect anywhere (SSRF).
        * The body read is capped at ``_MAX_PAGE_BYTES``; og:title sits in
          ``<head>``, so anything bigger is truncated, not buffered.
        """
        current = url
        for _ in range(_MAX_REDIRECT_HOPS + 1):
            try:
                async with self._client_factory() as client:
                    async with client.stream("GET", current) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            current = _bandcamp_redirect_target(
                                current, response.headers.get("location")
                            )
                            continue
                        if response.status_code == 429:
                            raise ResolverRateLimitError("upstream rate limit exceeded")
                        if response.status_code in (400, 404):
                            raise SongNotFoundError("could not resolve that link")
                        if response.status_code >= 500:
                            raise ResolverUnavailableError(
                                f"upstream returned {response.status_code}"
                            )
                        if response.status_code != 200:
                            raise ResolverUnavailableError(
                                f"unexpected upstream status {response.status_code}"
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) >= _MAX_PAGE_BYTES:
                                break
                        return bytes(body[:_MAX_PAGE_BYTES]).decode("utf-8", errors="replace")
            except httpx.TimeoutException as exc:
                raise ResolverTimeoutError("song lookup timed out") from exc
            except httpx.HTTPError as exc:
                raise ResolverUnavailableError("could not reach upstream") from exc
        raise SongNotFoundError("could not resolve that link")

    # ----------------------------------------------------------------- #
    # Deezer search funnel — title (+ optional artist) -> canonical identity.
    # ----------------------------------------------------------------- #
    async def _identify_via_deezer_search(self, title: str, artist: str | None) -> SongIdentity:
        try:
            result = await self._deezer.search(title, artist)
        except DeezerRateLimitError as exc:
            raise ResolverRateLimitError("rate limited, try again shortly") from exc
        except DeezerTimeoutError as exc:
            raise ResolverTimeoutError("song lookup timed out") from exc
        except DeezerUnavailableError as exc:
            raise ResolverUnavailableError("song lookup is unavailable") from exc
        except DeezerError as exc:
            raise SongNotFoundError("could not resolve that link") from exc

        if not result.results:
            raise SongNotFoundError("no matching track found")
        top = result.results[0]
        return SongIdentity(
            title=top.title,
            artist=top.artist,
            album=top.album,
            thumbnail_url=top.thumbnail_url,
            isrc=top.isrc,
        )

    # ----------------------------------------------------------------- #
    # Per-platform identification.
    # ----------------------------------------------------------------- #
    async def _resolve_deezer(self, track_id: str) -> SongIdentity:
        data = await self._get_json(_DEEZER_TRACK.format(id=quote(track_id)))
        if data.get("error") or not data.get("title"):
            raise SongNotFoundError("Deezer could not resolve that track")
        album = data.get("album") or {}
        artist = data.get("artist") or {}
        return SongIdentity(
            title=data["title"],
            artist=artist.get("name") or None,
            album=album.get("title") or None,
            thumbnail_url=album.get("cover_big") or album.get("cover") or None,
            isrc=data.get("isrc") or None,
        )

    async def _resolve_apple(self, track_id: str) -> SongIdentity:
        data = await self._get_json(_ITUNES_LOOKUP, {"id": track_id})
        results = data.get("results") or []
        if not results:
            raise SongNotFoundError("Apple Music track not found")
        item = results[0]
        name = item.get("trackName")
        if not name:
            raise SongNotFoundError("Apple Music track had no title")
        # iTunes carries no ISRC; funnel through Deezer for canonical identity.
        # Clean version suffixes ("(Full Length Version)") so the search matches.
        return await self._identify_via_deezer_search(
            _clean_title(name), item.get("artistName") or None
        )

    async def _resolve_spotify(self, url: str) -> SongIdentity:
        # Exact path: when Spotify is configured, look the track up by id via its
        # API — gives the real artist + ISRC, fixing the oEmbed-title mis-match
        # where "Serpents" fuzzy-searched to "Serpentskirt" (MYS-100).
        track_id = _spotify_track_id(urlparse(url).path)
        if track_id and self._spotify is not None:
            track = await self._spotify.track_identity_by_id(track_id)
            if track is not None:
                if track.isrc:
                    return SongIdentity(
                        title=track.title,
                        artist=track.artist,
                        album=track.album,
                        thumbnail_url=track.thumbnail_url,
                        isrc=track.isrc,
                    )
                # No ISRC on the Spotify record (rare): still use its exact
                # title+artist for an accurate Deezer match (gets the ISRC).
                return await self._identify_via_deezer_search(track.title, track.artist)

        # Fallback (Spotify unconfigured / lookup failed): oEmbed gives only the
        # track name (no artist), so search on the title alone. Weakest path.
        data = await self._get_json(_SPOTIFY_OEMBED, {"url": url})
        title = data.get("title")
        if not title:
            raise SongNotFoundError("Spotify track not found")
        return await self._identify_via_deezer_search(title, None)

    async def _resolve_youtube(self, url: str) -> SongIdentity:
        data = await self._get_json(_YOUTUBE_OEMBED, {"url": url, "format": "json"})
        title = data.get("title")
        if not title:
            raise SongNotFoundError("YouTube video not found")
        cleaned = _clean_title(title)
        # VEVO/official uploads title as "Artist - Title" — split that, since the
        # channel name is an unreliable artist hint. "Artist - Topic" auto-channels
        # instead carry the artist in the channel name (and a bare song title).
        if " - " in cleaned:
            artist_part, title_part = (p.strip() for p in cleaned.split(" - ", 1))
            return await self._identify_via_deezer_search(title_part, artist_part or None)
        return await self._identify_via_deezer_search(
            cleaned, _topic_artist(data.get("author_name"))
        )

    async def _resolve_bandcamp(self, url: str) -> SongIdentity:
        # No oEmbed and no public API — the track page's OpenGraph og:title
        # ("Track Title, by Artist Name") is the only keyless identity source.
        page = await self._get_text(url)
        og_title = _og_title(page)
        if not og_title:
            raise SongNotFoundError("Bandcamp track not found")
        # Split on the LAST ", by " — a title can itself contain ", by ", but
        # an artist name essentially never does.
        title, separator, artist = og_title.rpartition(", by ")
        if not separator:
            title, artist = og_title, ""
        return await self._identify_via_deezer_search(_clean_title(title), artist.strip() or None)

    # ----------------------------------------------------------------- #
    # Dispatch.
    # ----------------------------------------------------------------- #
    async def resolve(self, url: str) -> SongIdentity:
        """Identify the song behind ``url``. Raises a :class:`ResolverError`
        subclass on any failure (the router maps these to HTTP statuses)."""
        if not isinstance(url, str) or not _looks_like_url(url):
            raise InvalidSongURLError("a valid http(s) URL is required")

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        host = host.removeprefix("www.")
        path = parsed.path

        if host == "deezer.com" or host.endswith(".deezer.com"):
            track_id = _deezer_track_id(path)
            if track_id is None:
                raise InvalidSongURLError("not a Deezer track URL")
            return await self._resolve_deezer(track_id)

        if host == "music.apple.com":
            apple_id = parse_qs(parsed.query).get("i")
            if not apple_id or not apple_id[0]:
                raise InvalidSongURLError("Apple Music URL must reference a track (?i=)")
            return await self._resolve_apple(apple_id[0])

        if host == "open.spotify.com":
            if "/track/" not in path:
                raise InvalidSongURLError("not a Spotify track URL")
            return await self._resolve_spotify(url)

        if host in ("youtube.com", "music.youtube.com", "m.youtube.com", "youtu.be"):
            return await self._resolve_youtube(url)

        if _is_bandcamp_host(host):
            if "/track/" not in path:
                raise InvalidSongURLError("not a Bandcamp track URL")
            return await self._resolve_bandcamp(url)

        raise SongNotFoundError("unsupported or unrecognized music link")


def _deezer_track_id(path: str) -> str | None:
    """Extract a Deezer numeric track id from a URL path, or None.

    Handles both ``/track/{id}`` and localized ``/en/track/{id}`` forms."""
    match = re.search(r"/track/(\d+)", path)
    return match.group(1) if match else None


def _spotify_track_id(path: str) -> str | None:
    """Extract a Spotify base-62 track id from a ``/track/{id}`` path, or None."""
    match = re.search(r"/track/([A-Za-z0-9]+)", path)
    return match.group(1) if match else None


def build_link_resolver() -> LinkResolver:
    # Share one keyless Deezer client (its in-process cache) across resolves, and
    # the configured Spotify client for exact Spotify-link resolution (MYS-100).
    return LinkResolver(deezer=build_deezer_client(), spotify=get_spotify_client())


_RESOLVER: LinkResolver | None = None


def get_link_resolver() -> LinkResolver:
    """FastAPI dependency providing the paste-a-link resolver. Cached so the
    Deezer search cache survives across requests."""
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = build_link_resolver()
    return _RESOLVER
