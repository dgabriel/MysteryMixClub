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
Advanced query filters (used when an artist is supplied):
  q=artist:"<artist>" track:"<title>"
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache

import httpx
from pydantic import BaseModel

_SEARCH_URL = "https://api.deezer.com/search"
_DEFAULT_TIMEOUT = 10.0
_RESULT_LIMIT = 10
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
        # in a title/artist would corrupt the artist:"" track:"" grammar and
        # silently mis-/zero-match. Drop quotes; fuzzy match still lands the track.
        return f'artist:"{_strip_quotes(artist)}" track:"{_strip_quotes(title)}"'
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

        params: dict[str, str | int] = {"q": _build_query(title, artist), "limit": _RESULT_LIMIT}
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
        results = [t for t in (_track_from_item(item) for item in items) if t is not None]
        total = payload.get("total", len(results))
        too_many = artist is None and isinstance(total, int) and total > _RESULT_LIMIT

        result = SongSearchResult(results=results, too_many_results=too_many)
        self._cache.set(cache_key, result)
        return result


def build_deezer_client() -> DeezerSearchClient:
    return DeezerSearchClient()


@lru_cache
def get_deezer_client() -> DeezerSearchClient:
    """FastAPI dependency providing the Deezer search client. Cached so the
    in-process result cache survives across requests."""
    return build_deezer_client()
