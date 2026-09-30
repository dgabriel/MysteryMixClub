"""Song search that gets its ISRCs from Apple Music and its metadata from Deezer
(MysteryMixClub-etjx, ADR 0039).

Deezer's own search is the fragile link in song identification: its ``artist:``
filter died silently in September 2026 (MysteryMixClub-0ui0). Apple Music's
catalog search, called with only the server's developer token, was measured to
return the right artist and an ISRC for 15 of 15 real tracks, so it is asked
first. But Apple is used **only to obtain candidate ISRCs**. Every title, artist,
album, artwork URL and track identity that is displayed or persisted comes from
Deezer's exact ``/track/isrc:{isrc}`` lookup, so the shapes callers already
consume (:class:`~app.services.deezer_search.SongSearchResult`) are unchanged.

Consequences that look arbitrary without that context:

* A candidate Deezer cannot enrich is **omitted**, never shown with Apple's
  metadata. A gap is acceptable; a track whose identity came from two sources is
  not.
* Any Apple failure (no credentials, 429, timeout, rejected token) and any empty
  outcome falls back to Deezer's plain search, so the picker never gets worse than
  it was. Failures are logged and never cached as an empty result.
* ``SONG_SEARCH_PROVIDER=deezer`` switches Apple off with no code change.

The caller-visible error vocabulary stays Deezer's (``DeezerRateLimitError`` and
friends), since a fallback to Deezer is the last resort and the route and the
link resolver already map those to HTTP statuses.

Licensing: Apple's DPLA section 3.3.6(D) may restrict using catalog lookups for
purposes unrelated to Apple Music subscriptions. Pulling only ISRCs does not
resolve that; it is an open question with Apple, recorded in ADR 0039. This module
implements what was authorized; it is not a claim that the use is approved.
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.apple_music_client import (
    AppleCatalogSong,
    AppleMusicClient,
    AppleMusicError,
    CATALOG_SEARCH_LIMIT,
)
from app.services.deezer_search import (
    _CACHE_MAXSIZE,
    _CACHE_TTL_SECONDS,
    _RESULT_LIMIT,
    DeezerError,
    DeezerRateLimitError,
    DeezerSearchClient,
    SongSearchResult,
    SongTrack,
    _TTLCache,
    get_deezer_client,
)
from app.services.search_relevance import score

logger = logging.getLogger("app.services.song_search")

# Apple returns 25 rows for almost any query, including many unrelated songs by
# the same artist. Below this combined title/artist score a row is dropped rather
# than offered: 0.7 * title similarity + 0.3 * artist similarity, so a right-artist
# but unrelated-title row lands near 0.3-0.4 and a same-title wrong-artist row
# (which the user may genuinely want to choose between) stays well above.
_MIN_RELEVANCE = 0.5
# Concurrent Deezer ISRC lookups across the WHOLE service, not per search: many
# users searching at once must not multiply the load on Deezer. Concurrency is not
# a rate limit (Deezer allows 50 requests / 5 seconds per IP), so this only caps the
# burst; a 429 also stops the rest of that search's lookups (see ``_enrich``).
_ENRICH_CONCURRENCY = 5
# Search runs inside a user's request and must fail over to Deezer quickly, unlike
# playlist creation's 20 s.
_APPLE_TIMEOUT_SECONDS = 6.0
_STOREFRONT_RE = re.compile(r"^[a-z]{2}$")
_DEFAULT_STOREFRONT = "us"


def normalize_storefront(value: str | None, default: str = _DEFAULT_STOREFRONT) -> str:
    """A lowercase ISO 3166 alpha-2 storefront, or ``default`` for anything else.

    The value comes from a pasted URL or an env var, and ends up in a request
    path, so an unrecognized shape is replaced, never passed through.
    """
    candidate = (value or "").strip().lower()
    return candidate if _STOREFRONT_RE.match(candidate) else default


class SongSearchService:
    """Provider-selecting, fallback-guarded ``search(title, artist)``.

    Drop-in for :class:`DeezerSearchClient` wherever only ``search`` is used.
    """

    def __init__(
        self,
        *,
        deezer: DeezerSearchClient,
        apple: AppleMusicClient | None = None,
        provider: str = "apple",
        storefront: str = _DEFAULT_STOREFRONT,
        cache: _TTLCache | None = None,
    ) -> None:
        self._deezer = deezer
        self._apple = apple
        self._provider = provider
        self._storefront = normalize_storefront(storefront)
        self._cache = cache if cache is not None else _TTLCache(_CACHE_TTL_SECONDS, _CACHE_MAXSIZE)
        # Shared by every search this service runs (asyncio binds it to the running
        # loop on first use, so constructing it here, outside a loop, is fine).
        self._enrich_gate = asyncio.Semaphore(_ENRICH_CONCURRENCY)

    @property
    def apple_active(self) -> bool:
        """Whether Apple will be asked at all: selected AND credentials present."""
        return self._provider == "apple" and self._apple is not None and self._apple.is_configured

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #
    async def search(
        self, title: str, artist: str | None = None, storefront: str | None = None
    ) -> SongSearchResult:
        """Search by title (+ optional artist). Raises the ``Deezer*`` errors."""
        if not title or not title.strip() or not self.apple_active:
            # Empty input keeps Deezer's own validation error; an inactive Apple
            # is exactly the old behavior.
            return await self._deezer.search(title, artist)

        title = title.strip()
        artist = artist.strip() if artist else None
        front = normalize_storefront(storefront, self._storefront)
        cache_key = f"{front}\x1f{title.lower()}\x1f{(artist or '').lower()}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            result = await self._apple_search(title, artist, front)
        except AppleMusicError as exc:
            self._log_apple_failure(exc)
            result = None

        if result is not None and result.results:
            # Only a real, enriched hit is cached. A failure or an empty outcome
            # is never stored, so a transient Apple problem cannot be replayed
            # from cache as "no results" for ten minutes.
            self._cache.set(cache_key, result)
            return result
        return await self._deezer.search(title, artist)

    async def _apple_search(
        self, title: str, artist: str | None, storefront: str
    ) -> SongSearchResult | None:
        assert self._apple is not None  # apple_active guarantees this
        term = f"{title} {artist}" if artist else title
        songs = await self._apple.with_storefront(storefront).search_songs(term)

        candidates = self._candidates(title, artist, songs)
        if not candidates:
            return None
        tracks = await self._enrich(candidates)
        if not tracks:
            return None
        return SongSearchResult(
            results=tracks,
            # No artist and Apple filled its page: same "add an artist" cue the
            # Deezer path gives when it reports more matches than it returned.
            too_many_results=artist is None and len(songs) >= CATALOG_SEARCH_LIMIT,
        )

    @staticmethod
    def _candidates(
        title: str, artist: str | None, songs: list[AppleCatalogSong]
    ) -> list[AppleCatalogSong]:
        """Relevant candidates with a usable ISRC, best first, one per ISRC.

        Apple lists the same recording once per album/single/compilation, so the
        raw rows are full of duplicate ISRCs. Ranking stays with the shared
        relevance scorer; the threshold is what stops the first row being taken on
        faith when nothing in the page actually resembles the query.
        """
        scored = [
            (score(title, artist, song.title, song.artist), index, song)
            for index, song in enumerate(songs)
            if song.isrc
        ]
        scored.sort(key=lambda entry: (-entry[0], entry[1]))
        seen: set[str] = set()
        out: list[AppleCatalogSong] = []
        for relevance, _index, song in scored:
            if relevance < _MIN_RELEVANCE:
                break
            isrc = (song.isrc or "").upper()
            if isrc in seen:
                continue
            seen.add(isrc)
            out.append(song)
            if len(out) >= _RESULT_LIMIT:
                break
        return out

    async def _enrich(self, candidates: list[AppleCatalogSong]) -> list[SongTrack]:
        """Deezer metadata for each candidate ISRC, in candidate order.

        A candidate Deezer doesn't have, or fails to answer for, is dropped: Apple's
        own title/artist are never substituted. Distinct ISRCs can resolve to the
        same Deezer track, so the result is de-duplicated on Deezer's id too.
        """
        throttled = False

        async def lookup(song: AppleCatalogSong) -> SongTrack | None:
            nonlocal throttled
            async with self._enrich_gate:
                if throttled:
                    # Deezer already said 429 for this search: don't keep asking.
                    return None
                try:
                    return await self._deezer.lookup_isrc(song.isrc or "")
                except DeezerRateLimitError:
                    throttled = True
                    logger.warning("deezer rate limited ISRC enrichment; skipping the rest")
                    return None
                except DeezerError as exc:
                    logger.warning("deezer ISRC enrichment failed (%s)", type(exc).__name__)
                    return None

        looked_up = await asyncio.gather(*(lookup(song) for song in candidates))
        seen: set[str] = set()
        tracks: list[SongTrack] = []
        for track in looked_up:
            if track is None or track.id in seen:
                continue
            seen.add(track.id)
            tracks.append(track)
        return tracks

    # ------------------------------------------------------------------ #
    # Pasted Apple Music URL
    # ------------------------------------------------------------------ #
    async def identify_apple_song(
        self, song_id: str, storefront: str | None = None
    ) -> SongTrack | None:
        """Deezer-enriched identity for an Apple catalog song id, or ``None``.

        ``None`` means "use the existing path": Apple inactive or failing, the id
        not in that storefront's catalog, no ISRC, or Deezer not having that ISRC.
        It is never a signal that the song does not exist, and it never carries
        Apple's metadata.
        """
        if not self.apple_active:
            return None
        assert self._apple is not None
        front = normalize_storefront(storefront, self._storefront)
        try:
            song = await self._apple.with_storefront(front).catalog_song(song_id)
        except AppleMusicError as exc:
            self._log_apple_failure(exc)
            return None
        if song is None or not song.isrc:
            return None
        try:
            return await self._deezer.lookup_isrc(song.isrc)
        except DeezerError as exc:
            logger.warning("deezer ISRC enrichment failed (%s)", type(exc).__name__)
            return None

    @staticmethod
    def _log_apple_failure(exc: AppleMusicError) -> None:
        # The error's own fixed message only: never the token, the key, or the
        # user's query.
        logger.warning("apple catalog lookup failed, falling back to deezer: %s", exc)


def build_song_search_service(
    settings: Settings, deezer: DeezerSearchClient, apple: AppleMusicClient | None = None
) -> SongSearchService:
    if apple is None and settings.song_search_provider == "apple":
        from app.services.apple_music_token import get_apple_music_token_service

        apple = AppleMusicClient(get_apple_music_token_service(), timeout=_APPLE_TIMEOUT_SECONDS)
    return SongSearchService(
        deezer=deezer,
        apple=apple,
        provider=settings.song_search_provider,
        storefront=settings.song_search_apple_storefront,
    )


@lru_cache
def get_default_song_search_service() -> SongSearchService:
    """The process-wide service, shared by the picker route and the link resolver
    so both draw on one cache and one Deezer client."""
    return build_song_search_service(get_settings(), get_deezer_client())


def song_search_for(deezer: DeezerSearchClient) -> SongSearchService:
    """The service for the FastAPI dependency.

    In production the injected Deezer client is the single cached one, so this is
    the shared default service (one cache). Anything else is a test double, which
    gets a throwaway service: nothing to cache across requests, and no registry
    that would have to outlive it.
    """
    if deezer is get_deezer_client():
        return get_default_song_search_service()
    return build_song_search_service(get_settings(), deezer)
