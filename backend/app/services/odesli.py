"""Odesli / Songlink integration (MYS-44).

This module is the *only* place that knows the shape of an Odesli API response.
Callers (the router, and therefore the frontend) receive a small normalized
schema — :class:`ResolvedSong` — and never touch Odesli-specific fields such as
``entitiesByUniqueId`` or ``linksByPlatform``. A future swap to direct platform
APIs is a single-file change: keep ``ResolvedSong`` stable and rewrite the
internals here.

Reference: https://www.notion.so/Public-API-d0ebe08a5e304a55928405eb682f6741
``GET https://api.song.link/v1-alpha.1/links?url=<encoded url>&key=<api key>``
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings

_API_URL = "https://api.song.link/v1-alpha.1/links"
_DEFAULT_TIMEOUT = 10.0

# Odesli platform keys we surface, in display order. Odesli emits many more
# (tidal, amazonMusic, pandora, …); the product only cares about these four.
# Mapping value is the key we expose in our own schema — kept identical so the
# contract reads the same on both sides, but the indirection is deliberate so a
# rename never leaks an Odesli-ism to clients.
_PLATFORMS: dict[str, str] = {
    "spotify": "spotify",
    "youtube": "youtube",
    "deezer": "deezer",
    "appleMusic": "appleMusic",
}


class ResolvedSong(BaseModel):
    """Normalized, platform-agnostic song identity returned to callers."""

    title: str
    artist: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None
    isrc: str | None = None
    # Only platforms that actually have a link for this song are present.
    # Keys are a subset of {"spotify", "youtube", "deezer", "appleMusic"}.
    platforms: dict[str, str]


# --------------------------------------------------------------------------- #
# Errors — a small hierarchy the router maps to HTTP status codes. Callers
# catch these, never httpx exceptions, so the Odesli dependency stays sealed.
# --------------------------------------------------------------------------- #
class OdesliError(Exception):
    """Base class for all Odesli resolution failures."""


class InvalidSongURLError(OdesliError):
    """The supplied URL is malformed or not a resolvable music link (-> 400)."""


class SongNotFoundError(OdesliError):
    """Odesli could not match the URL to a song (-> 404)."""


class OdesliRateLimitError(OdesliError):
    """Odesli returned 429 — upstream rate limit hit (-> 429)."""


class OdesliTimeoutError(OdesliError):
    """The request to Odesli timed out (-> 504)."""


class OdesliUnavailableError(OdesliError):
    """Odesli returned an unexpected error or was unreachable (-> 502)."""


def _looks_like_url(value: str) -> bool:
    candidate = value.strip().lower()
    return candidate.startswith("http://") or candidate.startswith("https://")


def _extract_isrc(entities: dict[str, dict]) -> str | None:
    """First ISRC found across all entities. Odesli exposes it inconsistently —
    some providers populate ``isrc``, some ``isrcs`` — so we scan defensively."""
    for entity in entities.values():
        isrc = entity.get("isrc")
        if isinstance(isrc, str) and isrc:
            return isrc
        isrcs = entity.get("isrcs")
        if isinstance(isrcs, list) and isrcs:
            first = isrcs[0]
            if isinstance(first, str) and first:
                return first
    return None


def platforms_from_payload(payload: dict | None) -> dict[str, str]:
    """Extract the known-platform link map from a raw Odesli payload (e.g. a
    stored ``submissions.odesli_data``). Only platforms with a usable URL are
    included; returns ``{}`` for a missing/empty payload."""
    links = (payload or {}).get("linksByPlatform") or {}
    platforms: dict[str, str] = {}
    for odesli_key, out_key in _PLATFORMS.items():
        entry = links.get(odesli_key)
        if isinstance(entry, dict):
            url = entry.get("url")
            if isinstance(url, str) and url:
                platforms[out_key] = url
    return platforms


def _normalize(payload: dict) -> ResolvedSong:
    entities: dict[str, dict] = payload.get("entitiesByUniqueId") or {}

    primary_id = payload.get("entityUniqueId")
    primary = entities.get(primary_id) if isinstance(primary_id, str) else None
    if primary is None and entities:
        primary = next(iter(entities.values()))
    if not primary:
        raise SongNotFoundError("no song entity in Odesli response")

    title = primary.get("title")
    if not isinstance(title, str) or not title:
        raise SongNotFoundError("Odesli response had no song title")

    return ResolvedSong(
        title=title,
        artist=primary.get("artistName") or None,
        # Odesli rarely carries an album name; surface it when present.
        album=primary.get("album") or primary.get("albumName") or None,
        thumbnail_url=primary.get("thumbnailUrl") or None,
        isrc=_extract_isrc(entities),
        platforms=platforms_from_payload(payload),
    )


class OdesliClient:
    """Async wrapper around the Odesli ``/links`` endpoint.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a
    mock transport; in production it defaults to a real client with a timeout.
    """

    def __init__(
        self,
        api_key: str = "",
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))

    async def _fetch_raw(self, url: str) -> dict:
        """Call Odesli and return the raw JSON payload. Raises an
        :class:`OdesliError` subclass on any failure."""
        if not isinstance(url, str) or not _looks_like_url(url):
            raise InvalidSongURLError("a valid http(s) URL is required")

        params = {"url": url, "userCountry": "US"}
        if self._api_key:
            params["key"] = self._api_key

        try:
            async with self._client_factory() as client:
                response = await client.get(_API_URL, params=params)
        except httpx.TimeoutException as exc:
            raise OdesliTimeoutError("Odesli request timed out") from exc
        except httpx.HTTPError as exc:
            raise OdesliUnavailableError("could not reach Odesli") from exc

        if response.status_code == 429:
            raise OdesliRateLimitError("Odesli rate limit exceeded")
        if response.status_code in (400, 404):
            # Odesli answers both a malformed URL and an unmatched song with 4xx.
            raise SongNotFoundError("Odesli could not resolve that link")
        if response.status_code >= 500:
            raise OdesliUnavailableError(f"Odesli returned {response.status_code}")
        if response.status_code != 200:
            raise OdesliUnavailableError(f"unexpected Odesli status {response.status_code}")

        try:
            return response.json()
        except ValueError as exc:
            raise OdesliUnavailableError("Odesli returned a non-JSON body") from exc

    async def resolve(self, url: str) -> ResolvedSong:
        """Resolve a platform URL to a normalized song. Used only to identify a
        *pasted* link (title/artist/isrc); cross-service links are assembled
        separately by :mod:`app.services.song_links`."""
        return _normalize(await self._fetch_raw(url))


def build_odesli_client(settings: Settings) -> OdesliClient:
    return OdesliClient(api_key=settings.odesli_api_key)


def get_odesli_client() -> OdesliClient:
    """FastAPI dependency providing the configured Odesli client."""
    return build_odesli_client(get_settings())
