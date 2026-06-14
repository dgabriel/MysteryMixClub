"""Spotify search integration (MYS-44).

Client-credentials auth (no user login) + track search. Like :mod:`odesli`,
this module fully owns the Spotify response shape: callers receive
:class:`SpotifySearchResult` and never see Spotify JSON. The access token is
cached in-process until shortly before it expires.

Reference:
  Auth:   POST https://accounts.spotify.com/api/token  (grant_type=client_credentials)
  Search: GET  https://api.spotify.com/v1/search?type=track&q=<query>&limit=10
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import lru_cache

import httpx
from pydantic import BaseModel

from app.config import Settings, get_settings

_TOKEN_URL = "https://accounts.spotify.com/api/token"  # noqa: S105 - public endpoint, not a secret
_SEARCH_URL = "https://api.spotify.com/v1/search"
_DEFAULT_TIMEOUT = 10.0
_RESULT_LIMIT = 10
# Refresh a little before the real expiry so an in-flight search never races it.
_TOKEN_EXPIRY_SKEW = 30.0


class SpotifyTrack(BaseModel):
    id: str
    title: str
    artist: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None
    spotify_url: str | None = None


class SpotifySearchResult(BaseModel):
    results: list[SpotifyTrack]
    # True only when the caller gave no artist and Spotify reports more than
    # _RESULT_LIMIT total matches — the cue to prompt for an artist name.
    too_many_results: bool = False


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class SpotifyError(Exception):
    """Base class for all Spotify search failures."""


class SpotifyAuthError(SpotifyError):
    """Client credentials missing or rejected (-> 502)."""


class SpotifyRateLimitError(SpotifyError):
    """Spotify returned 429 (-> 429)."""


class SpotifyTimeoutError(SpotifyError):
    """A request to Spotify timed out (-> 504)."""


class SpotifyUnavailableError(SpotifyError):
    """Spotify returned an unexpected error or was unreachable (-> 502)."""


def _build_query(title: str, artist: str | None) -> str:
    # Spotify field filters narrow the match when we know the artist.
    query = f"track:{title}"
    if artist:
        query += f" artist:{artist}"
    return query


def _smallest_image(images: list) -> str | None:
    # Spotify returns images largest-first; the last is the thumbnail-sized one.
    urls = [img.get("url") for img in images if isinstance(img, dict) and img.get("url")]
    return urls[-1] if urls else None


def _track_from_item(item: dict) -> SpotifyTrack | None:
    track_id = item.get("id")
    name = item.get("name")
    if not track_id or not name:
        return None
    artists = item.get("artists") or []
    artist = ", ".join(a.get("name") for a in artists if a.get("name")) or None
    album_obj = item.get("album") or {}
    return SpotifyTrack(
        id=track_id,
        title=name,
        artist=artist,
        album=album_obj.get("name") or None,
        thumbnail_url=_smallest_image(album_obj.get("images") or []),
        spotify_url=(item.get("external_urls") or {}).get("spotify"),
    )


class SpotifySearchClient:
    """Authenticated Spotify track search with an in-process token cache."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        if not self._client_id or not self._client_secret:
            raise SpotifyAuthError("Spotify client credentials are not configured")

        try:
            async with self._client_factory() as client:
                response = await client.post(
                    _TOKEN_URL,
                    data={"grant_type": "client_credentials"},
                    auth=(self._client_id, self._client_secret),
                )
        except httpx.TimeoutException as exc:
            raise SpotifyTimeoutError("Spotify auth timed out") from exc
        except httpx.HTTPError as exc:
            raise SpotifyUnavailableError("could not reach Spotify auth") from exc

        if response.status_code in (400, 401, 403):
            raise SpotifyAuthError("Spotify rejected the client credentials")
        if response.status_code != 200:
            raise SpotifyUnavailableError(f"Spotify auth returned {response.status_code}")

        data = response.json()
        token = data.get("access_token")
        if not token:
            raise SpotifyAuthError("Spotify auth response had no access token")
        self._token = token
        self._token_expires_at = (
            time.monotonic() + float(data.get("expires_in", 3600)) - _TOKEN_EXPIRY_SKEW
        )
        return token

    async def search(self, title: str, artist: str | None = None) -> SpotifySearchResult:
        """Search tracks by title (+ optional artist). Returns up to 10 tracks
        and flags ``too_many_results`` when an artist would help disambiguate."""
        if not title or not title.strip():
            raise SpotifyError("a non-empty title is required")

        token = await self._access_token()
        params = {
            "q": _build_query(title.strip(), artist.strip() if artist else None),
            "type": "track",
            "limit": _RESULT_LIMIT,
        }
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    _SEARCH_URL,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.TimeoutException as exc:
            raise SpotifyTimeoutError("Spotify search timed out") from exc
        except httpx.HTTPError as exc:
            raise SpotifyUnavailableError("could not reach Spotify search") from exc

        if response.status_code == 429:
            raise SpotifyRateLimitError("Spotify rate limit exceeded")
        if response.status_code == 401:
            raise SpotifyAuthError("Spotify access token was rejected")
        if response.status_code != 200:
            raise SpotifyUnavailableError(f"Spotify search returned {response.status_code}")

        tracks_obj = response.json().get("tracks") or {}
        items = tracks_obj.get("items") or []
        results = [t for t in (_track_from_item(item) for item in items) if t is not None]
        total = tracks_obj.get("total", len(results))
        too_many = artist is None and isinstance(total, int) and total > _RESULT_LIMIT

        return SpotifySearchResult(results=results, too_many_results=too_many)


def build_spotify_client(settings: Settings) -> SpotifySearchClient:
    return SpotifySearchClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
    )


@lru_cache
def get_spotify_client() -> SpotifySearchClient:
    """FastAPI dependency providing the configured Spotify search client.

    Cached so the in-process access-token cache survives across requests rather
    than re-authenticating on every search.
    """
    return build_spotify_client(get_settings())
