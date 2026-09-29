"""SongSearchService: Apple ISRCs, Deezer metadata, Deezer fallback
(MysteryMixClub-etjx, ADR 0039).

Both upstreams are faked at the client boundary, so this exercises the
orchestration: candidate filtering and de-duplication, enrichment, storefront
handling, caching and every fallback path. The one rule that matters most is
asserted repeatedly: nothing Apple says is ever displayed. A track's title, artist,
album, art and identity come from Deezer or the track is omitted.
"""

import asyncio

import pytest

from app.services.apple_music_client import (
    AppleCatalogSong,
    AppleMusicApiError,
    AppleMusicRateLimitError,
    AppleMusicUnavailableError,
)
from app.services.deezer_search import (
    DeezerRateLimitError,
    DeezerTimeoutError,
    DeezerUnavailableError,
    SongSearchResult,
    SongTrack,
)
from app.services.song_search import SongSearchService, normalize_storefront


def _apple(song_id, title, artist, isrc):
    return AppleCatalogSong(id=song_id, title=title, artist=artist, isrc=isrc)


def _deezer_track(deezer_id, title, artist, isrc, *, album="Deezer Album"):
    return SongTrack(
        id=str(deezer_id),
        title=title,
        artist=artist,
        album=album,
        thumbnail_url=f"https://deezer.img/{deezer_id}.jpg",
        isrc=isrc,
        resolve_url=f"https://www.deezer.com/track/{deezer_id}",
    )


class _FakeApple:
    """Stands in for AppleMusicClient. ``with_storefront`` returns the same object
    after recording the storefront, so calls stay observable on one instance."""

    def __init__(self, songs=None, *, configured=True, error=None, song=None):
        self._songs = songs or []
        self._configured = configured
        self._error = error
        self._song = song
        self.searches: list[tuple[str, str]] = []  # (storefront, term)
        self.lookups: list[tuple[str, str]] = []  # (storefront, song id)
        self._storefront = "us"

    @property
    def is_configured(self) -> bool:
        return self._configured

    def with_storefront(self, storefront):
        self._storefront = storefront
        return self

    async def search_songs(self, term):
        self.searches.append((self._storefront, term))
        if self._error is not None:
            raise self._error
        return self._songs

    async def catalog_song(self, song_id):
        self.lookups.append((self._storefront, song_id))
        if self._error is not None:
            raise self._error
        return self._song


class _FakeDeezer:
    """Stands in for DeezerSearchClient: exact ISRC lookups plus a plain search."""

    def __init__(self, by_isrc=None, *, search_results=None, lookup_error=None, search_error=None):
        self._by_isrc = by_isrc or {}
        self._search_results = search_results or []
        self._lookup_error = lookup_error
        self._search_error = search_error
        self.lookups: list[str] = []
        self.searches: list[tuple[str, str | None]] = []
        self._in_flight = 0
        self.max_in_flight = 0

    async def lookup_isrc(self, isrc):
        self.lookups.append(isrc)
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(0)  # let concurrent lookups overlap
            err = self._lookup_error
            if isinstance(err, dict):
                err = err.get(isrc)
            if err is not None:
                raise err
            return self._by_isrc.get(isrc)
        finally:
            self._in_flight -= 1

    async def search(self, title, artist=None):
        self.searches.append((title, artist))
        if self._search_error is not None:
            raise self._search_error
        return SongSearchResult(results=self._search_results)


_FALLBACK = _deezer_track(999, "Fallback Song", "Fallback Artist", "USFALLBACK01")


def _service(apple, deezer, **kwargs) -> SongSearchService:
    return SongSearchService(deezer=deezer, apple=apple, **kwargs)


def _pepper_world():
    apple = _FakeApple([_apple("a1", "Pepper", "Butthole Surfers", "USCA29600428")])
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(3643236, "Pepper", "Butthole Surfers", "USCA29600428")}
    )
    return apple, deezer


# --------------------------------------------------------------------------- #
# Identification + enrichment
# --------------------------------------------------------------------------- #


async def test_apple_isrc_is_enriched_with_deezer_metadata():
    apple, deezer = _pepper_world()
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert [t.id for t in result.results] == ["3643236"]
    track = result.results[0]
    assert (track.title, track.artist, track.album) == (
        "Pepper",
        "Butthole Surfers",
        "Deezer Album",
    )
    assert track.thumbnail_url == "https://deezer.img/3643236.jpg"
    assert track.resolve_url == "https://www.deezer.com/track/3643236"
    assert track.isrc == "USCA29600428"
    assert deezer.searches == []  # Deezer's search is not consulted on a hit
    assert apple.searches == [("us", "Pepper Butthole Surfers")]


async def test_apple_metadata_is_never_displayed():
    # Apple spells everything differently; only Deezer's spelling may surface.
    apple = _FakeApple([_apple("a1", "PEPPER (APPLE TITLE)", "APPLE ARTIST", "USCA29600428")])
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(1, "Pepper (Deezer Title)", "Deezer Artist", "USCA29600428")}
    )
    # Relevance runs on Apple's row, so query with Apple's own words to pass it.
    result = await _service(apple, deezer).search("PEPPER (APPLE TITLE)", "APPLE ARTIST")

    track = result.results[0]
    assert track.title == "Pepper (Deezer Title)"
    assert track.artist == "Deezer Artist"
    dumped = str(result.model_dump())
    assert "APPLE" not in dumped


async def test_no_artist_searches_the_bare_title():
    apple, deezer = _pepper_world()
    await _service(apple, deezer).search("Pepper")
    assert apple.searches == [("us", "Pepper")]


async def test_candidate_order_follows_relevance_not_apples_order():
    apple = _FakeApple(
        [
            _apple("1", "Pepper Spray", "Butthole Surfers", "USB00000001"),
            _apple("2", "Pepper", "Butthole Surfers", "USA00000002"),
        ]
    )
    deezer = _FakeDeezer(
        {
            "USB00000001": _deezer_track(11, "Pepper Spray", "Butthole Surfers", "USB00000001"),
            "USA00000002": _deezer_track(22, "Pepper", "Butthole Surfers", "USA00000002"),
        }
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert [t.title for t in result.results][0] == "Pepper"


# --------------------------------------------------------------------------- #
# Duplicates
# --------------------------------------------------------------------------- #


async def test_duplicate_isrcs_are_looked_up_once():
    # The same recording appears once per album/single/compilation.
    apple = _FakeApple(
        [
            _apple("1", "Pepper", "Butthole Surfers", "USCA29600428"),
            _apple("2", "Pepper", "Butthole Surfers", "usca29600428"),
            _apple("3", "Pepper", "Butthole Surfers", "USCA29600428"),
        ]
    )
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(1, "Pepper", "Butthole Surfers", "USCA29600428")}
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert len(result.results) == 1
    assert deezer.lookups == ["USCA29600428"]


async def test_distinct_isrcs_that_share_a_deezer_track_collapse_to_one():
    apple = _FakeApple(
        [
            _apple("1", "Pepper", "Butthole Surfers", "USCA29600428"),
            _apple("2", "Pepper", "Butthole Surfers", "USCA29699999"),
        ]
    )
    same = _deezer_track(3643236, "Pepper", "Butthole Surfers", "USCA29600428")
    deezer = _FakeDeezer({"USCA29600428": same, "USCA29699999": same})
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert [t.id for t in result.results] == ["3643236"]


async def test_results_are_capped_at_ten():
    songs = [_apple(str(i), "Pepper", "Butthole Surfers", f"USCA2960{i:04d}") for i in range(25)]
    deezer = _FakeDeezer(
        {
            f"USCA2960{i:04d}": _deezer_track(i, "Pepper", "Butthole Surfers", f"USCA2960{i:04d}")
            for i in range(25)
        }
    )
    result = await _service(_FakeApple(songs), deezer).search("Pepper", "Butthole Surfers")
    assert len(result.results) == 10
    assert len(deezer.lookups) == 10  # bounded before enrichment, not after


# --------------------------------------------------------------------------- #
# Missing Deezer matches
# --------------------------------------------------------------------------- #


async def test_candidate_deezer_lacks_is_omitted_not_filled_from_apple():
    apple = _FakeApple(
        [
            _apple("1", "Pepper", "Butthole Surfers", "USCA29600428"),
            _apple("2", "Pepper Spray", "Butthole Surfers", "USNOTONDEEZER"),
        ]
    )
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(1, "Pepper", "Butthole Surfers", "USCA29600428")}
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert [t.title for t in result.results] == ["Pepper"]
    assert "Pepper Spray" not in str(result.model_dump())


async def test_no_candidate_deezer_has_falls_back_to_deezer_search():
    apple = _FakeApple([_apple("1", "Pepper", "Butthole Surfers", "USCA29600428")])
    deezer = _FakeDeezer({}, search_results=[_FALLBACK])
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert result.results == [_FALLBACK]
    assert deezer.searches == [("Pepper", "Butthole Surfers")]


async def test_some_enrichment_failures_are_omitted_and_the_rest_kept():
    apple = _FakeApple(
        [
            _apple("1", "Pepper", "Butthole Surfers", "USCA29600428"),
            _apple("2", "Pepper", "Butthole Surfers", "USBAD0000001"),
        ]
    )
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(1, "Pepper", "Butthole Surfers", "USCA29600428")},
        lookup_error={"USBAD0000001": DeezerTimeoutError("slow")},
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert [t.id for t in result.results] == ["1"]


@pytest.mark.parametrize(
    "error", [DeezerRateLimitError("q"), DeezerTimeoutError("t"), DeezerUnavailableError("u")]
)
async def test_deezer_failing_for_every_lookup_falls_through_to_deezer_search(error):
    apple, _ = _pepper_world()
    deezer = _FakeDeezer(lookup_error=error, search_results=[_FALLBACK])
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert result.results == [_FALLBACK]


async def test_deezer_outage_surfaces_the_deezer_error_not_a_swallowed_empty_result():
    # Enrichment fails AND the fallback search fails: the route must see the
    # Deezer error (502/429/504), not an empty picker.
    apple, _ = _pepper_world()
    deezer = _FakeDeezer(
        lookup_error=DeezerUnavailableError("down"), search_error=DeezerUnavailableError("down")
    )
    with pytest.raises(DeezerUnavailableError):
        await _service(apple, deezer).search("Pepper", "Butthole Surfers")


# --------------------------------------------------------------------------- #
# Relevance filtering
# --------------------------------------------------------------------------- #


async def test_unrelated_rows_are_dropped_not_taken_on_faith():
    # Right artist, unrelated titles: exactly what Apple pads a page with.
    apple = _FakeApple(
        [
            _apple("1", "Completely Different Tune", "Butthole Surfers", "USAAA0000001"),
            _apple("2", "Another Unrelated Song", "Butthole Surfers", "USAAA0000002"),
        ]
    )
    deezer = _FakeDeezer(
        {
            "USAAA0000001": _deezer_track(1, "Completely Different Tune", "X", "USAAA0000001"),
            "USAAA0000002": _deezer_track(2, "Another Unrelated Song", "X", "USAAA0000002"),
        },
        search_results=[_FALLBACK],
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert deezer.lookups == []  # never even enriched
    assert result.results == [_FALLBACK]


async def test_same_title_by_another_artist_still_reaches_the_user():
    # A wrong-artist row is the user's call to make from the list, so it survives.
    apple = _FakeApple([_apple("1", "Cannibal", "Ke$ha", "USRC10900001")])
    deezer = _FakeDeezer({"USRC10900001": _deezer_track(5, "Cannibal", "Ke$ha", "USRC10900001")})
    result = await _service(apple, deezer).search("Cannibal", "Marcus Mumford")
    assert [t.artist for t in result.results] == ["Ke$ha"]


async def test_rows_without_an_isrc_are_ignored():
    apple = _FakeApple(
        [
            _apple("1", "Pepper", "Butthole Surfers", None),
            _apple("2", "Pepper", "Butthole Surfers", ""),
        ]
    )
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert deezer.lookups == []
    assert result.results == [_FALLBACK]


async def test_version_markers_the_query_did_not_ask_for_rank_below_the_original():
    apple = _FakeApple(
        [
            _apple("1", "Pepper (Karaoke Version)", "Butthole Surfers", "USKAR0000001"),
            _apple("2", "Pepper", "Butthole Surfers", "USORG0000002"),
        ]
    )
    deezer = _FakeDeezer(
        {
            "USKAR0000001": _deezer_track(1, "Pepper (Karaoke Version)", "X", "USKAR0000001"),
            "USORG0000002": _deezer_track(2, "Pepper", "X", "USORG0000002"),
        }
    )
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")
    assert result.results[0].title == "Pepper"


# --------------------------------------------------------------------------- #
# Credentials / provider selection
# --------------------------------------------------------------------------- #


async def test_no_credentials_never_calls_apple():
    apple, deezer = _pepper_world()
    apple._configured = False
    deezer._search_results = [_FALLBACK]
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert apple.searches == []
    assert result.results == [_FALLBACK]


async def test_no_apple_client_at_all_is_plain_deezer():
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    result = await SongSearchService(deezer=deezer, apple=None).search("x", "y")
    assert result.results == [_FALLBACK]


async def test_provider_deezer_switches_apple_off_without_a_code_change():
    apple, deezer = _pepper_world()
    deezer._search_results = [_FALLBACK]
    service = _service(apple, deezer, provider="deezer")

    assert service.apple_active is False
    result = await service.search("Pepper", "Butthole Surfers")
    assert apple.searches == []
    assert result.results == [_FALLBACK]


async def test_empty_title_keeps_deezers_own_validation_error():
    from app.services.deezer_search import DeezerError

    class _Strict(_FakeDeezer):
        async def search(self, title, artist=None):
            raise DeezerError("a non-empty title is required")

    apple, _ = _pepper_world()
    with pytest.raises(DeezerError):
        await _service(apple, _Strict()).search("   ")
    assert apple.searches == []


# --------------------------------------------------------------------------- #
# Upstream failures, rate limits, fallback
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "error",
    [
        AppleMusicRateLimitError("429"),
        AppleMusicUnavailableError("down"),
        AppleMusicApiError("400"),
    ],
)
async def test_apple_failures_fall_back_to_deezer(error):
    apple = _FakeApple(error=error)
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    result = await _service(apple, deezer).search("Pepper", "Butthole Surfers")

    assert result.results == [_FALLBACK]
    assert deezer.lookups == []


async def test_apple_failure_is_never_cached_as_an_empty_result():
    apple = _FakeApple(error=AppleMusicRateLimitError("429"))
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    service = _service(apple, deezer)

    await service.search("Pepper", "Butthole Surfers")
    apple._error = None
    apple._songs = [_apple("1", "Pepper", "Butthole Surfers", "USCA29600428")]
    deezer._by_isrc = {
        "USCA29600428": _deezer_track(3643236, "Pepper", "Butthole Surfers", "USCA29600428")
    }
    recovered = await service.search("Pepper", "Butthole Surfers")

    assert len(apple.searches) == 2  # the failure did not poison the cache
    assert [t.id for t in recovered.results] == ["3643236"]


async def test_empty_apple_outcome_is_not_cached_either():
    apple = _FakeApple([])
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    service = _service(apple, deezer)

    await service.search("Nothing", "Nobody")
    await service.search("Nothing", "Nobody")
    assert len(apple.searches) == 2


async def test_fallback_results_are_left_to_deezers_own_cache_not_ours():
    apple = _FakeApple(error=AppleMusicUnavailableError("down"))
    deezer = _FakeDeezer(search_results=[_FALLBACK])
    service = _service(apple, deezer)

    await service.search("Pepper", "Butthole Surfers")
    await service.search("Pepper", "Butthole Surfers")
    assert len(apple.searches) == 2  # Apple is retried; only a real hit is cached


# --------------------------------------------------------------------------- #
# Cache + storefront
# --------------------------------------------------------------------------- #


async def test_successful_search_is_cached():
    apple, deezer = _pepper_world()
    service = _service(apple, deezer)

    first = await service.search("Pepper", "Butthole Surfers")
    second = await service.search("Pepper", "Butthole Surfers")

    assert second == first
    assert len(apple.searches) == 1
    assert len(deezer.lookups) == 1


async def test_cache_key_ignores_case_and_surrounding_whitespace():
    apple, deezer = _pepper_world()
    service = _service(apple, deezer)
    await service.search("Pepper", "Butthole Surfers")
    await service.search("  pepper ", " BUTTHOLE SURFERS")
    assert len(apple.searches) == 1


async def test_cache_is_keyed_by_storefront():
    apple, deezer = _pepper_world()
    service = _service(apple, deezer)

    await service.search("Pepper", "Butthole Surfers", storefront="us")
    await service.search("Pepper", "Butthole Surfers", storefront="gb")
    await service.search("Pepper", "Butthole Surfers", storefront="gb")

    assert [sf for sf, _ in apple.searches] == ["us", "gb"]


async def test_configured_default_storefront_is_used_when_none_given():
    apple, deezer = _pepper_world()
    await _service(apple, deezer, storefront="de").search("Pepper", "Butthole Surfers")
    assert apple.searches[0][0] == "de"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GB", "gb"),
        (" jp ", "jp"),
        ("", "us"),
        (None, "us"),
        ("usa", "us"),
        ("u", "us"),
        ("1a", "us"),
        ("../", "us"),
    ],
)
def test_normalize_storefront_only_lets_two_letters_through(raw, expected):
    assert normalize_storefront(raw) == expected


async def test_junk_storefront_from_a_caller_is_replaced_before_reaching_apple():
    apple, deezer = _pepper_world()
    await _service(apple, deezer).search("Pepper", "Butthole Surfers", storefront="../../x")
    assert apple.searches[0][0] == "us"


# --------------------------------------------------------------------------- #
# Bounded concurrency + too_many_results
# --------------------------------------------------------------------------- #


async def test_enrichment_concurrency_is_bounded():
    songs = [_apple(str(i), "Pepper", "Butthole Surfers", f"USCA2960{i:04d}") for i in range(10)]
    deezer = _FakeDeezer(
        {
            f"USCA2960{i:04d}": _deezer_track(i, "Pepper", "Butthole Surfers", f"USCA2960{i:04d}")
            for i in range(10)
        }
    )
    await _service(_FakeApple(songs), deezer).search("Pepper", "Butthole Surfers")

    assert len(deezer.lookups) == 10
    assert 1 < deezer.max_in_flight <= 5


async def test_enrichment_concurrency_is_bounded_across_simultaneous_searches():
    # The bound is process-wide: many users searching at once must not multiply the
    # load on Deezer. A per-search limit would allow 3 searches x 5 = 15 in flight.
    class _PerArtistApple(_FakeApple):
        async def search_songs(self, term):
            artist = term.split()[-1]
            return [
                _apple(f"{artist}{i}", "Pepper", artist, f"US{artist}{i:07d}") for i in range(8)
            ]

    by_isrc = {
        f"US{artist}{i:07d}": _deezer_track(f"{artist}{i}", "Pepper", artist, f"US{artist}{i:07d}")
        for artist in ("AAA", "BBB", "CCC")
        for i in range(8)
    }
    deezer = _FakeDeezer(by_isrc)
    service = _service(_PerArtistApple(), deezer)

    results = await asyncio.gather(
        service.search("Pepper", "AAA"),
        service.search("Pepper", "BBB"),
        service.search("Pepper", "CCC"),
    )

    assert all(len(r.results) == 8 for r in results)
    assert len(deezer.lookups) == 24
    assert deezer.max_in_flight <= 5


async def test_a_deezer_429_stops_the_rest_of_that_searchs_lookups():
    songs = [_apple(str(i), "Pepper", "Butthole Surfers", f"USCA2960{i:04d}") for i in range(10)]
    deezer = _FakeDeezer(
        lookup_error=DeezerRateLimitError("quota"), search_error=DeezerRateLimitError("quota")
    )
    with pytest.raises(DeezerRateLimitError):
        await _service(_FakeApple(songs), deezer).search("Pepper", "Butthole Surfers")

    # The gate admits 5 at once; after the first 429 the queued ones skip Deezer.
    assert len(deezer.lookups) < 10


async def test_too_many_results_only_without_an_artist_and_a_full_apple_page():
    songs = [_apple(str(i), "Pepper", "Artist", f"USCA2960{i:04d}") for i in range(25)]
    deezer = _FakeDeezer(
        {
            f"USCA2960{i:04d}": _deezer_track(i, "Pepper", "Artist", f"USCA2960{i:04d}")
            for i in range(25)
        }
    )
    no_artist = await _service(_FakeApple(songs), deezer).search("Pepper")
    with_artist = await _service(_FakeApple(songs), deezer).search("Pepper", "Artist")

    assert no_artist.too_many_results is True
    assert with_artist.too_many_results is False


# --------------------------------------------------------------------------- #
# identify_apple_song -- a pasted Apple Music URL
# --------------------------------------------------------------------------- #


async def test_identify_apple_song_resolves_through_the_catalog_then_deezer():
    apple = _FakeApple(song=_apple("724788539", "APPLE TITLE", "APPLE ARTIST", "USCA29600428"))
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(3643236, "Pepper", "Butthole Surfers", "USCA29600428")}
    )
    track = await _service(apple, deezer).identify_apple_song("724788539", "gb")

    assert track is not None and track.title == "Pepper" and track.artist == "Butthole Surfers"
    assert apple.lookups == [("gb", "724788539")]  # the URL's storefront, not the default
    assert deezer.lookups == ["USCA29600428"]


async def test_identify_apple_song_defaults_and_sanitizes_the_storefront():
    apple = _FakeApple(song=None)
    service = _service(apple, _FakeDeezer(), storefront="fr")
    await service.identify_apple_song("1", None)
    await service.identify_apple_song("2", "not-a-storefront")
    assert [sf for sf, _ in apple.lookups] == ["fr", "fr"]


async def test_identify_apple_song_uses_no_search_cache_and_no_apple_metadata_on_deezer_miss():
    apple = _FakeApple(song=_apple("1", "APPLE TITLE", "APPLE ARTIST", "USCA29600428"))
    assert await _service(apple, _FakeDeezer({})).identify_apple_song("1") is None


@pytest.mark.parametrize(
    "apple",
    [
        _FakeApple(error=AppleMusicRateLimitError("429")),
        _FakeApple(error=AppleMusicUnavailableError("down")),
        _FakeApple(song=None),
        _FakeApple(song=_apple("1", "T", "A", None)),
        _FakeApple(configured=False, song=_apple("1", "T", "A", "USCA29600428")),
    ],
)
async def test_identify_apple_song_returns_none_so_the_caller_uses_the_old_path(apple):
    deezer = _FakeDeezer(
        {"USCA29600428": _deezer_track(1, "Pepper", "Butthole Surfers", "USCA29600428")}
    )
    assert await _service(apple, deezer).identify_apple_song("1") is None


async def test_identify_apple_song_deezer_failure_is_none_not_an_exception():
    apple = _FakeApple(song=_apple("1", "T", "A", "USCA29600428"))
    deezer = _FakeDeezer(lookup_error=DeezerUnavailableError("down"))
    assert await _service(apple, deezer).identify_apple_song("1") is None


async def test_identify_apple_song_with_provider_deezer_never_calls_apple():
    apple = _FakeApple(song=_apple("1", "T", "A", "USCA29600428"))
    service = _service(apple, _FakeDeezer(), provider="deezer")
    assert await service.identify_apple_song("1") is None
    assert apple.lookups == []
