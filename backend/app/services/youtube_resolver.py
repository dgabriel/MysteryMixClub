"""YouTube Data API resolver (MYS-78).

Resolves a song (title + optional artist) to a single YouTube video id via the
YouTube Data API ``search.list`` endpoint. Like :mod:`odesli` / :mod:`song_links`
this module fully owns the upstream response shape; callers only ever see a bare
video id string (or ``None``).

Resolution is best-effort by design: a missing API key, quota/auth failure,
timeout, or empty result all yield ``None`` so a submission is never blocked and
the playlist GET never fails on one bad track.

Reference: https://developers.google.com/youtube/v3/docs/search/list
  GET https://www.googleapis.com/youtube/v3/search
      ?part=snippet&q=<query>&type=video&maxResults=1&key=<api key>
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import httpx

from app.config import Settings, get_settings

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_DEFAULT_TIMEOUT = 10.0


def _query(title: str, artist: str | None) -> str:
    return f"{title} {artist}".strip() if artist else title.strip()


class YouTubeResolver:
    """Resolves a song to a YouTube video id via the YouTube Data API.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a
    mock transport; in production it defaults to a real client with a timeout.
    Resolution never raises — any failure returns ``None``.
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

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        """Top YouTube video id for ``title`` (+ optional ``artist``), or ``None``.

        Returns ``None`` for: an unconfigured API key, an empty title, a non-200
        response (quota/auth/etc.), no items, a timeout, or any transport/parse
        error. Best-effort — never raises to the caller."""
        if not self._api_key or not title or not title.strip():
            return None

        params: dict[str, str | int] = {
            "part": "snippet",
            "q": _query(title, artist),
            "type": "video",
            "maxResults": 1,
            "key": self._api_key,
        }
        try:
            async with self._client_factory() as client:
                response = await client.get(_SEARCH_URL, params=params)
        except httpx.HTTPError:
            # Timeouts are a subclass of HTTPError; both are swallowed.
            return None

        if response.status_code != 200:
            return None

        try:
            payload = response.json()
        except ValueError:
            return None

        items = payload.get("items") or []
        if not items:
            return None
        video_id = (items[0].get("id") or {}).get("videoId")
        if isinstance(video_id, str) and video_id:
            return video_id
        return None


def build_youtube_resolver(settings: Settings) -> YouTubeResolver:
    return YouTubeResolver(api_key=settings.youtube_api_key)


@lru_cache
def get_youtube_resolver() -> YouTubeResolver:
    """FastAPI dependency providing the configured YouTube resolver."""
    return build_youtube_resolver(get_settings())
