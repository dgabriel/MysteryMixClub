"""YouTube Data API resolver (MYS-78).

Resolves a song (title + optional artist) to a single YouTube video id via the
YouTube Data API ``search.list`` endpoint. Like :mod:`link_resolver` /
:mod:`song_links` this module fully owns the upstream response shape; callers only ever see a bare
video id string (or ``None``).

Resolution is best-effort by design: a missing API key, quota/auth failure,
timeout, or empty result all yield ``None`` so a submission is never blocked and
the playlist GET never fails on one bad track.

The API's own top hit is frequently an unrelated or non-original video
(MYS-175), so several candidates are fetched and the closest title match to
the query is chosen, rather than trusting ``search.list``'s own ordering.

Reference: https://developers.google.com/youtube/v3/docs/search/list
  GET https://www.googleapis.com/youtube/v3/search
      ?part=snippet&q=<query>&type=video&maxResults=5&key=<api key>
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import httpx

from app.config import Settings, get_settings
from app.services.search_relevance import best_match

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_DEFAULT_TIMEOUT = 10.0
_RESULT_LIMIT = 5


@dataclass(frozen=True)
class YouTubeLookup:
    """One resolve attempt's outcome (ADR 0015).

    ``answered`` separates the two ways ``video_id`` can be ``None``:

    * ``answered=True``  — YouTube responded and nothing matched. A verdict on
      the track; safe to record and stop asking.
    * ``answered=False`` — the question never got through (quota 403, timeout,
      transport error, unconfigured key). Says nothing about the track, and
      must not be recorded as an attempt.
    """

    video_id: str | None
    answered: bool


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
        error. Best-effort — never raises to the caller.

        Callers that need to tell "YouTube has no match" apart from "YouTube
        wouldn't answer" must use :meth:`resolve` instead — this method
        deliberately flattens both to ``None``."""
        return (await self.resolve(title, artist)).video_id

    async def resolve(self, title: str, artist: str | None = None) -> YouTubeLookup:
        """Same lookup as :meth:`video_id_for`, but reporting *why* it came back
        empty (ADR 0015).

        The distinction is load-bearing for the backfill: a genuine "searched,
        nothing matched" is a final answer worth recording, while a quota 403,
        a timeout, or an unconfigured key means the question was never actually
        asked. Recording the second kind as an answer is how a whole batch of
        resolvable tracks gets permanently written off during an outage — which
        is exactly what happened the first time this ran against a spent quota.
        """
        if not self._api_key or not title or not title.strip():
            # Nothing was asked, so nothing was answered — an unconfigured
            # deployment must not poison every submission it sees.
            return YouTubeLookup(video_id=None, answered=False)

        query = _query(title, artist)
        params: dict[str, str | int] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": _RESULT_LIMIT,
            "key": self._api_key,
        }
        try:
            async with self._client_factory() as client:
                response = await client.get(_SEARCH_URL, params=params)
        except httpx.HTTPError:
            # Timeouts are a subclass of HTTPError; both are swallowed.
            return YouTubeLookup(video_id=None, answered=False)

        if response.status_code != 200:
            # Quota exhaustion (403), auth failures, and 5xx all land here.
            return YouTubeLookup(video_id=None, answered=False)

        try:
            payload = response.json()
        except ValueError:
            return YouTubeLookup(video_id=None, answered=False)

        items = payload.get("items") or []
        if not items:
            # A real, empty result set: YouTube answered, it just has nothing.
            return YouTubeLookup(video_id=None, answered=True)
        # Video titles interleave artist + title (e.g. "Artist - Song (Audio)"),
        # so the full query is matched against the whole snippet title rather
        # than splitting title/artist like the other providers. The uploading
        # channel is matched against the artist as the secondary (0.3-weight)
        # signal, so the artist's own channel is preferred over a same-song
        # reupload from an unrelated channel when one is present (MYS-175).
        chosen = best_match(
            query,
            artist,
            items,
            title_of=lambda item: (item.get("snippet") or {}).get("title") or "",
            artist_of=lambda item: (item.get("snippet") or {}).get("channelTitle"),
        )
        # Answered from here down: YouTube returned candidates, so a rejection
        # below is our own ranking calling them all unrelated (MYS-175) — a real
        # verdict on this track, not an upstream failure.
        if chosen is None:
            return YouTubeLookup(video_id=None, answered=True)
        video_id = (chosen.get("id") or {}).get("videoId")
        if isinstance(video_id, str) and video_id:
            return YouTubeLookup(video_id=video_id, answered=True)
        return YouTubeLookup(video_id=None, answered=True)


def build_youtube_resolver(settings: Settings) -> YouTubeResolver:
    return YouTubeResolver(api_key=settings.youtube_api_key)


@lru_cache
def get_youtube_resolver() -> YouTubeResolver:
    """FastAPI dependency providing the configured YouTube resolver."""
    return build_youtube_resolver(get_settings())
