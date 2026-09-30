"""Deezer search integration (MYS-44).

Keyless, free song search. Like :mod:`song_links`, this module fully owns the
Deezer response shape — callers get a normalized :class:`SongSearchResult` and
never see Deezer JSON. Each result carries its ISRC (Deezer returns it inline) so
the canonical-identity goal is met at search time, plus a ``resolve_url`` (the
Deezer track URL). The keyless paste-a-link resolver (:mod:`link_resolver`) also
reuses this search to recover an ISRC for Apple/Spotify/YouTube links.

Results are cached in-process (TTL) so popular searches don't re-hit Deezer —
the scaling lever that lets a small upstream budget serve a large audience.

Reference: https://developers.deezer.com/api/search
  GET https://api.deezer.com/search?q=<query>&limit=10
Query shape when an artist is supplied:
  q=track:"<title>" <artist>
The artist rides along as a plain term. Deezer's ``artist:"..."`` filter stopped
matching anything around 2026-09-23 (HTTP 200, empty ``data``, no error), while
the ``track:"..."`` filter still works.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from functools import lru_cache

import httpx
from pydantic import BaseModel

from app.services.search_relevance import rank as _rank_candidates

logger = logging.getLogger("app.services.deezer_search")

_SEARCH_URL = "https://api.deezer.com/search"
_TRACK_BY_ISRC_URL = "https://api.deezer.com/track/isrc:{isrc}"
# ISO 3901: 2 letters (country) + 3 alphanumerics (registrant) + 7 digits.
_ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
# Deezer's "no data" error code, returned with HTTP 200 for an unknown lookup.
_DEEZER_NOT_FOUND_CODE = 800
_DEFAULT_TIMEOUT = 10.0
_RESULT_LIMIT = 10
# With an artist, Deezer only uses it as a loose hint (the artist: filter is dead,
# see _build_query), so a common title fills a 10-row page with other artists'
# songs ("If", "Cocoon", "Swan Song"). Fetch a wider page, let the ranker pull the
# right artist up, then trim back to _RESULT_LIMIT. Measured on a real 15-track
# club: top-10 hit rate 11/15 at limit 10 vs 14/15 at limit 50.
_ARTIST_FETCH_LIMIT = 50
_CACHE_TTL_SECONDS = 600.0
_CACHE_MAXSIZE = 256
# Deezer signals quota/rate-limit as an error body (HTTP 200) with code 4.
_DEEZER_QUOTA_CODE = 4


class SongTrack(BaseModel):
    id: str
    title: str
    artist: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None
    isrc: str | None = None
    # The Deezer track URL handed to /resolve when this track is selected.
    resolve_url: str | None = None


class SongSearchResult(BaseModel):
    results: list[SongTrack]
    # True only when the caller gave no artist and Deezer reports more than
    # _RESULT_LIMIT total matches — the cue to prompt for an artist name.
    too_many_results: bool = False


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class DeezerError(Exception):
    """Base class for all Deezer search failures."""


class DeezerRateLimitError(DeezerError):
    """Deezer quota / rate limit hit (-> 429)."""


class DeezerTimeoutError(DeezerError):
    """A request to Deezer timed out (-> 504)."""


class DeezerUnavailableError(DeezerError):
    """Deezer returned an unexpected error or was unreachable (-> 502)."""


class _TTLCache:
    """Tiny insertion-ordered TTL cache. Not thread-safe; fine for asyncio."""

    def __init__(self, ttl: float, maxsize: int) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict[str, tuple[float, SongSearchResult]] = {}

    def get(self, key: str) -> SongSearchResult | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: SongSearchResult) -> None:
        if len(self._store) >= self._maxsize and key not in self._store:
            # Evict the oldest inserted entry.
            self._store.pop(next(iter(self._store)), None)
        self._store[key] = (time.monotonic() + self._ttl, value)


def _build_query(title: str, artist: str | None) -> str:
    if artist:
        # Deezer's advanced filter has no quote escaping, so a stray double-quote
        # in a title/artist would corrupt the track:"" grammar and silently
        # mis-/zero-match. Drop quotes; fuzzy match still lands the track.
        # The artist is a plain term, not artist:"" -- that filter returns nothing
        # since 2026-09-23 (MysteryMixClub-0ui0). Re-ranking sorts out the rest.
        return f'track:"{_strip_quotes(title)}" {_strip_quotes(artist)}'
    return title.replace('"', " ").strip() or title


def _strip_quotes(value: str) -> str:
    return value.replace('"', " ").strip()


def _track_from_item(item: dict) -> SongTrack | None:
    track_id = item.get("id")
    title = item.get("title")
    if track_id is None or not title:
        return None
    album = item.get("album") or {}
    artist = item.get("artist") or {}
    return SongTrack(
        id=str(track_id),
        title=title,
        artist=artist.get("name") or None,
        album=album.get("title") or None,
        thumbnail_url=album.get("cover_medium") or album.get("cover") or None,
        isrc=item.get("isrc") or None,
        resolve_url=item.get("link") or None,
    )


class DeezerSearchClient:
    """Keyless Deezer track search with an in-process TTL cache."""

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        cache: _TTLCache | None = None,
    ) -> None:
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._cache = cache if cache is not None else _TTLCache(_CACHE_TTL_SECONDS, _CACHE_MAXSIZE)

    async def search(self, title: str, artist: str | None = None) -> SongSearchResult:
        """Search tracks by title (+ optional artist). Returns up to 10 tracks and
        flags ``too_many_results`` when an artist would help disambiguate."""
        if not title or not title.strip():
            raise DeezerError("a non-empty title is required")

        title = title.strip()
        artist = artist.strip() if artist else None
        cache_key = f"{title.lower()}\x1f{(artist or '').lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, str | int] = {
            "q": _build_query(title, artist),
            "limit": _ARTIST_FETCH_LIMIT if artist else _RESULT_LIMIT,
        }
        try:
            async with self._client_factory() as client:
                response = await client.get(_SEARCH_URL, params=params)
        except httpx.TimeoutException as exc:
            raise DeezerTimeoutError("Deezer search timed out") from exc
        except httpx.HTTPError as exc:
            raise DeezerUnavailableError("could not reach Deezer") from exc

        if response.status_code != 200:
            raise DeezerUnavailableError(f"Deezer search returned {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise DeezerUnavailableError("Deezer returned a non-JSON body") from exc

        # Deezer reports quota/errors in the body with HTTP 200.
        error = payload.get("error")
        if error:
            if error.get("code") == _DEEZER_QUOTA_CODE:
                raise DeezerRateLimitError("Deezer quota exceeded")
            raise DeezerUnavailableError(f"Deezer error: {error.get('message', 'unknown')}")

        items = payload.get("data") or []
        if artist and not items:
            # Deezer answers a query it can't parse with a clean 200 and an empty
            # list (that is how the artist: filter broke unnoticed). A real miss is
            # possible too, so this is a canary to count, not proof. No query text:
            # it is user input.
            logger.warning("deezer returned zero results for an artist-qualified search")
        results = [t for t in (_track_from_item(item) for item in items) if t is not None]
        total = payload.get("total", len(results))
        # Deezer returns results in its own relevance order, which frequently
        # surfaces covers/karaoke/live versions above the original recording
        # (MYS-175). Re-rank against the query before returning.
        results = _rank_candidates(
            title, artist, results, title_of=lambda t: t.title, artist_of=lambda t: t.artist
        )[:_RESULT_LIMIT]
        too_many = artist is None and isinstance(total, int) and total > _RESULT_LIMIT

        result = SongSearchResult(results=results, too_many_results=too_many)
        self._cache.set(cache_key, result)
        return result

    async def lookup_isrc(self, isrc: str) -> SongTrack | None:
        """Exact Deezer track for an ISRC, or ``None`` if Deezer has none.

        The enrichment step for ISRCs found elsewhere (Apple Music, ADR 0039):
        Deezer supplies the title, artist, album and artwork that are shown and
        stored. Only a genuine "no such ISRC" is ``None``; quota, timeout and
        upstream failures raise, so a caller never mistakes an outage for a miss.
        """
        isrc = isrc.strip().upper()
        if not _ISRC_RE.match(isrc):
            return None
        try:
            async with self._client_factory() as client:
                response = await client.get(_TRACK_BY_ISRC_URL.format(isrc=isrc))
        except httpx.TimeoutException as exc:
            raise DeezerTimeoutError("Deezer ISRC lookup timed out") from exc
        except httpx.HTTPError as exc:
            raise DeezerUnavailableError("could not reach Deezer") from exc

        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise DeezerUnavailableError(f"Deezer ISRC lookup returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DeezerUnavailableError("Deezer returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise DeezerUnavailableError("Deezer returned an unreadable track")

        error = payload.get("error")
        if error:
            code = error.get("code") if isinstance(error, dict) else None
            if code == _DEEZER_NOT_FOUND_CODE:
                return None
            if code == _DEEZER_QUOTA_CODE:
                raise DeezerRateLimitError("Deezer quota exceeded")
            raise DeezerUnavailableError("Deezer returned an error for the ISRC lookup")

        track = _track_from_item(payload)
        if track is None:
            return None
        if track.isrc and track.isrc.upper() != isrc:
            # Never hand back a different recording than the one asked for: the
            # whole point of enriching by ISRC is that the identity is exact.
            return None
        return track.model_copy(update={"isrc": track.isrc or isrc})


def build_deezer_client() -> DeezerSearchClient:
    return DeezerSearchClient()


@lru_cache
def get_deezer_client() -> DeezerSearchClient:
    """FastAPI dependency providing the Deezer search client. Cached so the
    in-process result cache survives across requests."""
    return build_deezer_client()
