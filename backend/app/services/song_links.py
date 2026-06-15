"""Cross-service link assembler (MYS-52).

Builds platform links for a song from keyless sources, instead of resolving them
through Odesli (which, keyless, won't cross-match Spotify/YouTube/Apple from a
Deezer-sourced track). Anchored on title+artist, with ISRC used only where a
platform indexes it cleanly — ISRC is per-recording, so it's a tiebreaker, not
the master key (see MYS-52).

Per platform:
- Deezer     — exact track link via ``/track/isrc:{isrc}`` (else search); keyless.
- Apple Music— exact track link via the iTunes Search API (``trackViewUrl``); keyless.
- Spotify    — universal open-on-service deep link (keyless).
- YouTube    — universal open-on-service deep link (keyless).

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

_DEEZER_SEARCH = "https://api.deezer.com/search"
_DEEZER_TRACK_ISRC = "https://api.deezer.com/track/isrc:{isrc}"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
_DEFAULT_TIMEOUT = 10.0

# Platform display order matches the rest of the app's normalized schema.
PLATFORM_KEYS = ("spotify", "appleMusic", "deezer", "youtube")


def _query(title: str, artist: str | None) -> str:
    return f"{title} {artist}".strip() if artist else title.strip()


def _spotify_deeplink(q: str) -> str:
    return f"https://open.spotify.com/search/{quote(q)}"


def _youtube_deeplink(q: str) -> str:
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
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))

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

    async def _deezer_exact(self, q: str, isrc: str | None) -> str | None:
        # Prefer the ISRC lookup (precise); fall back to a title+artist search.
        if isrc:
            data = await self._get_json(_DEEZER_TRACK_ISRC.format(isrc=quote(isrc)))
            if data and not data.get("error") and data.get("link"):
                return data["link"]
        data = await self._get_json(_DEEZER_SEARCH, {"q": q, "limit": 1})
        if data and not data.get("error"):
            items = data.get("data") or []
            if items and items[0].get("link"):
                return items[0]["link"]
        return None

    async def _apple_exact(self, q: str) -> str | None:
        data = await self._get_json(_ITUNES_SEARCH, {"term": q, "entity": "song", "limit": 1})
        if data and data.get("resultCount"):
            return data["results"][0].get("trackViewUrl")
        return None

    async def assemble(
        self, title: str, artist: str | None = None, isrc: str | None = None
    ) -> dict[str, str]:
        """Return a ``{platform: url}`` map covering spotify/appleMusic/deezer/
        youtube. Exact links where a keyless lookup succeeds, else deep links."""
        q = _query(title, artist)
        deezer = await self._deezer_exact(q, isrc)
        apple = await self._apple_exact(q)
        return {
            "spotify": _spotify_deeplink(q),
            "appleMusic": apple or _apple_deeplink(q),
            "deezer": deezer or _deezer_deeplink(q),
            "youtube": _youtube_deeplink(q),
        }


@lru_cache
def get_link_assembler() -> SongLinkAssembler:
    """FastAPI dependency providing the link assembler."""
    return SongLinkAssembler()
