"""Cross-service link assembler (MYS-52).

Builds platform links for a song from keyless sources, instead of resolving them
through Odesli (which, keyless, won't cross-match Spotify/YouTube/Apple from a
Deezer-sourced track). Anchored on title+artist, with ISRC used only where a
platform indexes it cleanly — ISRC is per-recording, so it's a tiebreaker, not
the master key (see MYS-52).

Per platform:
- Deezer      — exact track link via ``/track/isrc:{isrc}`` (else search, ranked
                against the query — MYS-175); keyless.
- Apple Music — exact track link via the iTunes Search API, ranked against the
                query rather than trusting iTunes' own top hit (MYS-175); keyless.
- Spotify     — universal open-on-service deep link (keyless).
- YouTube     — exact video link via the YouTube Data API when a resolver is
                configured (ranked, MYS-175); falls back to a deep link when
                unconfigured or unmatched.
- YouTube Music — the same resolved video id, served through music.youtube.com
                instead of youtube.com, for players who prefer the Music app
                (MYS-175). Falls back to a YouTube Music search deep link under
                the same conditions as the YouTube entry.

Every platform always gets at least a deep link; exact links replace them when a
keyless lookup succeeds. Lookups are best-effort: a failure falls back to the
deep link rather than raising. Adding Spotify client credentials later upgrades
the Spotify entry to an exact link with no change to callers.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from urllib.parse import quote

import httpx

from app.services.search_relevance import best_match
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

_DEEZER_SEARCH = "https://api.deezer.com/search"
_DEEZER_TRACK_ISRC = "https://api.deezer.com/track/isrc:{isrc}"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
_DEFAULT_TIMEOUT = 10.0
# Candidate pool widened from 1 so a best-match pick is possible (MYS-175).
_DEEZER_RESULT_LIMIT = 5
_APPLE_RESULT_LIMIT = 5

# Platform display order matches the rest of the app's normalized schema.
PLATFORM_KEYS = ("spotify", "appleMusic", "deezer", "youtube", "youtubeMusic")


class _Unresolved:
    """Sentinel for ``assemble``'s ``youtube_video_id`` param, distinct from a
    resolved-but-empty ``None``."""


_UNRESOLVED = _Unresolved()


def _query(title: str, artist: str | None) -> str:
    return f"{title} {artist}".strip() if artist else title.strip()


def _spotify_deeplink(q: str) -> str:
    return f"https://open.spotify.com/search/{quote(q)}"


def _youtube_video_deeplink(q: str) -> str:
    return f"https://www.youtube.com/results?search_query={quote(q)}"


def _youtube_music_deeplink(q: str) -> str:
    return f"https://music.youtube.com/search?q={quote(q)}"


def _deezer_deeplink(q: str) -> str:
    return f"https://www.deezer.com/search/{quote(q)}"


def _apple_deeplink(q: str) -> str:
    return f"https://music.apple.com/search?term={quote(q)}"


class SongLinkAssembler:
    """Assembles cross-service platform links from keyless sources.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a
    mock transport; in production it defaults to a real client with a timeout.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        youtube_resolver: YouTubeResolver | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._youtube_resolver = youtube_resolver

    async def _get_json(self, url: str, params: dict | None = None) -> dict | None:
        """Best-effort GET returning parsed JSON, or None on any failure."""
        try:
            async with self._client_factory() as client:
                resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return None

    async def _deezer_exact(self, title: str, artist: str | None, isrc: str | None) -> str | None:
        # Prefer the ISRC lookup (precise); fall back to a ranked title+artist search.
        if isrc:
            data = await self._get_json(_DEEZER_TRACK_ISRC.format(isrc=quote(isrc)))
            if data and not data.get("error") and data.get("link"):
                return data["link"]
        q = _query(title, artist)
        data = await self._get_json(_DEEZER_SEARCH, {"q": q, "limit": _DEEZER_RESULT_LIMIT})
        if data and not data.get("error"):
            items = data.get("data") or []
            chosen = best_match(
                title,
                artist,
                items,
                title_of=lambda item: item.get("title") or "",
                artist_of=lambda item: (item.get("artist") or {}).get("name"),
            )
            if chosen and chosen.get("link"):
                return chosen["link"]
        return None

    async def _apple_exact(self, title: str, artist: str | None) -> str | None:
        q = _query(title, artist)
        data = await self._get_json(
            _ITUNES_SEARCH, {"term": q, "entity": "song", "limit": _APPLE_RESULT_LIMIT}
        )
        if not data or not data.get("resultCount"):
            return None
        results = data.get("results") or []
        chosen = best_match(
            title,
            artist,
            results,
            title_of=lambda item: item.get("trackName") or "",
            artist_of=lambda item: item.get("artistName"),
        )
        return chosen.get("trackViewUrl") if chosen else None

    async def _youtube_video_id(self, title: str, artist: str | None) -> str | None:
        if self._youtube_resolver is None:
            return None
        return await self._youtube_resolver.video_id_for(title, artist)

    async def assemble(
        self,
        title: str,
        artist: str | None = None,
        isrc: str | None = None,
        *,
        youtube_video_id: str | None | _Unresolved = _UNRESOLVED,
    ) -> dict[str, str]:
        """Return a ``{platform: url}`` map covering spotify/appleMusic/deezer/
        youtube/youtubeMusic. Exact links where a keyless lookup succeeds, else
        deep links.

        ``youtube_video_id``, when passed, is used as-is instead of resolving it
        again — callers that also need the bare video id (e.g. to persist it
        alongside the links, MYS-78/MYS-175) should resolve it once themselves
        and pass it through here to avoid a second YouTube Data API call."""
        q = _query(title, artist)
        deezer = await self._deezer_exact(title, artist, isrc)
        apple = await self._apple_exact(title, artist)
        video_id = (
            await self._youtube_video_id(title, artist)
            if youtube_video_id is _UNRESOLVED
            else youtube_video_id
        )
        return {
            "spotify": _spotify_deeplink(q),
            "appleMusic": apple or _apple_deeplink(q),
            "deezer": deezer or _deezer_deeplink(q),
            "youtube": (
                f"https://www.youtube.com/watch?v={video_id}"
                if video_id
                else _youtube_video_deeplink(q)
            ),
            "youtubeMusic": (
                f"https://music.youtube.com/watch?v={video_id}"
                if video_id
                else _youtube_music_deeplink(q)
            ),
        }


@lru_cache
def get_link_assembler() -> SongLinkAssembler:
    """FastAPI dependency providing the link assembler."""
    return SongLinkAssembler(youtube_resolver=get_youtube_resolver())
