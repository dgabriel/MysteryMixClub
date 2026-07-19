"""Cross-service link assembler (MYS-52).

Builds platform links for a song from keyless sources, instead of resolving them
through Odesli (which, keyless, won't cross-match Spotify/YouTube/Apple from a
Deezer-sourced track). Anchored on title+artist, with ISRC used only where a
platform indexes it cleanly — ISRC is per-recording, so it's a tiebreaker, not
the master key (see MYS-52).

Per platform:
- Deezer      — exact track link via ``/track/isrc:{isrc}`` (else search, ranked
                against the query — MYS-175); keyless.
- Apple Music — exact track link via the Apple Music catalog's ``filter[isrc]``
                when a developer token is configured (MYS-106); otherwise, and
                on any miss, the keyless iTunes Search API ranked against the
                query rather than trusting iTunes' own top hit (MYS-175).
- Spotify     — universal open-on-service deep link (keyless).
- YouTube     — exact video link via the YouTube Data API when a resolver is
                configured (ranked, MYS-175); falls back to a deep link when
                unconfigured or unmatched.
- YouTube Music — the same resolved video id, served through music.youtube.com
                instead of youtube.com, for players who prefer the Music app
                (MYS-175). Falls back to a YouTube Music search deep link under
                the same conditions as the YouTube entry.
- Bandcamp    — search deep link only (MYS-200). Bandcamp's API is partner-only,
                so there is nothing keyless to resolve an exact link against.

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

from app.services.apple_music_client import (
    CATALOG_SONGS_URL,
    DEFAULT_STOREFRONT,
    pick_catalog_song,
)
from app.services.apple_music_token import (
    AppleMusicTokenError,
    AppleMusicTokenService,
    get_apple_music_token_service,
)
from app.services.search_relevance import best_match
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

_DEEZER_SEARCH = "https://api.deezer.com/search"
_DEEZER_TRACK_ISRC = "https://api.deezer.com/track/isrc:{isrc}"
_ITUNES_SEARCH = "https://itunes.apple.com/search"
# Apple scopes the catalog per storefront. This path has no Music User Token to
# read the caller's storefront from, so it resolves against the default; a track
# missing there falls back to the keyless iTunes path (MYS-106).
_DEFAULT_TIMEOUT = 10.0
# Candidate pool widened from 1 so a best-match pick is possible (MYS-175).
_DEEZER_RESULT_LIMIT = 5
_APPLE_RESULT_LIMIT = 5

# Platform display order matches the rest of the app's normalized schema.
PLATFORM_KEYS = ("spotify", "appleMusic", "deezer", "youtube", "youtubeMusic", "bandcamp")


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


def _bandcamp_deeplink(q: str) -> str:
    # item_type=t scopes the search to tracks.
    return f"https://bandcamp.com/search?q={quote(q)}&item_type=t"


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
        apple_token_service: AppleMusicTokenService | None = None,
        storefront: str = DEFAULT_STOREFRONT,
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._youtube_resolver = youtube_resolver
        self._apple_token_service = apple_token_service
        self._storefront = storefront

    async def _get_json(
        self, url: str, params: dict | None = None, *, headers: dict | None = None
    ) -> dict | None:
        """Best-effort GET returning parsed JSON, or None on any failure."""
        try:
            async with self._client_factory() as client:
                resp = await client.get(url, params=params, headers=headers)
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

    async def _apple_catalog_isrc(self, title: str, artist: str | None, isrc: str) -> str | None:
        """Exact Apple catalog link for an ISRC, or None to fall back (MYS-106).

        Returns None whenever Apple Music isn't configured or the lookup doesn't
        land, so the caller drops to the keyless iTunes path unchanged.
        """
        service = self._apple_token_service
        if service is None or not service.is_configured:
            return None
        try:
            token = await service.get_developer_token()
        except AppleMusicTokenError:
            # Credentials present but unusable (malformed key, rotation mid-flight).
            # Best-effort like every other lookup here: fall back, don't raise.
            return None
        data = await self._get_json(
            CATALOG_SONGS_URL.format(storefront=self._storefront),
            {"filter[isrc]": isrc},
            headers={"Authorization": f"Bearer {token}"},
        )
        # One ISRC maps to several catalog songs more often than not — the same
        # recording reissued across album/EP/single — so rank rather than taking
        # Apple's first. Shared with the playlist path so both pick the same one.
        chosen = pick_catalog_song(title, artist, data)
        return (chosen.get("attributes") or {}).get("url") if chosen else None

    async def _apple_exact(self, title: str, artist: str | None, isrc: str | None) -> str | None:
        if isrc:
            exact = await self._apple_catalog_isrc(title, artist, isrc)
            if exact:
                return exact
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
        youtube/youtubeMusic/bandcamp. Exact links where a keyless lookup
        succeeds, else deep links.

        ``youtube_video_id``, when passed, is used as-is instead of resolving it
        again — callers that also need the bare video id (e.g. to persist it
        alongside the links, MYS-78/MYS-175) should resolve it once themselves
        and pass it through here to avoid a second YouTube Data API call."""
        q = _query(title, artist)
        deezer = await self._deezer_exact(title, artist, isrc)
        apple = await self._apple_exact(title, artist, isrc)
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
            # Deep-link-only: Bandcamp has no public API to look an exact link
            # up against (MYS-200).
            "bandcamp": _bandcamp_deeplink(q),
        }


@lru_cache
def get_link_assembler() -> SongLinkAssembler:
    """FastAPI dependency providing the link assembler."""
    return SongLinkAssembler(
        youtube_resolver=get_youtube_resolver(),
        apple_token_service=get_apple_music_token_service(),
    )
