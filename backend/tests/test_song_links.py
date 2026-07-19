"""Unit tests for app.services.song_links (MYS-52).

HTTP is mocked via httpx.MockTransport. Covers the assembled platform map:
Spotify/YouTube deep links (always), Deezer exact via ISRC then search then
deep-link fallback, Apple exact via iTunes then deep-link fallback, and
best-effort behaviour when an upstream errors.
"""

import httpx

from app.services.apple_music_token import AppleMusicTokenError
from app.services.song_links import SongLinkAssembler

_DEEZER_ISRC_OK = {"id": 1, "link": "https://www.deezer.com/track/111", "isrc": "USXYZ"}
_DEEZER_SEARCH_OK = {"data": [{"id": 2, "link": "https://www.deezer.com/track/222"}], "total": 1}
_ITUNES_OK = {"resultCount": 1, "results": [{"trackViewUrl": "https://music.apple.com/track/333"}]}


def _catalog_song(name, artist, url, album=None):
    """Shape one entry of an Apple Music catalog `/songs` response."""
    return {
        "id": url.rsplit("/", 1)[-1],
        "attributes": {"name": name, "artistName": artist, "albumName": album, "url": url},
    }


class _Dispatch:
    def __init__(self, *, isrc=None, search=None, itunes=None, catalog=None):
        self.isrc = isrc
        self.search = search
        self.itunes = itunes
        self.catalog = catalog
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.deezer.com" and path.startswith("/track/isrc:"):
            return self.isrc or httpx.Response(404)
        if host == "api.deezer.com" and path == "/search":
            return self.search or httpx.Response(200, json={"data": [], "total": 0})
        if host == "api.music.apple.com":
            return self.catalog or httpx.Response(200, json={"data": []})
        if host == "itunes.apple.com":
            return self.itunes or httpx.Response(200, json={"resultCount": 0, "results": []})
        return httpx.Response(404)

    def hosts(self) -> list[str]:
        return [c.url.host for c in self.calls]


class _FakeAppleTokenService:
    """Stub matching AppleMusicTokenService's interface, without signing anything."""

    def __init__(self, token: str | None = "dev-token"):
        # token=None models configured-but-unusable credentials (raises on mint).
        self._token = token

    @property
    def is_configured(self) -> bool:
        return True

    async def get_developer_token(self) -> str:
        if self._token is None:
            raise AppleMusicTokenError("boom")
        return self._token


class _UnconfiguredAppleTokenService(_FakeAppleTokenService):
    @property
    def is_configured(self) -> bool:
        return False


def _assembler(dispatch, *, youtube_resolver=None, apple_token_service=None) -> SongLinkAssembler:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)

    return SongLinkAssembler(
        client_factory=factory,
        youtube_resolver=youtube_resolver,
        apple_token_service=apple_token_service,
    )


class _FakeYouTubeResolver:
    """Stub matching YouTubeResolver's interface for injection into the assembler."""

    def __init__(self, video_id: str | None):
        self._video_id = video_id

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        return self._video_id


async def test_assemble_returns_all_six_platforms():
    a = _assembler(
        _Dispatch(
            isrc=httpx.Response(200, json=_DEEZER_ISRC_OK),
            itunes=httpx.Response(200, json=_ITUNES_OK),
        )
    )
    links = await a.assemble("Blinding Lights", "The Weeknd", "USUG11904206")
    assert set(links) == {"spotify", "appleMusic", "deezer", "youtube", "youtubeMusic", "bandcamp"}


async def test_spotify_and_youtube_are_deep_links():
    links = await _assembler(_Dispatch()).assemble("bad guy", "Billie Eilish")
    assert links["spotify"] == "https://open.spotify.com/search/bad%20guy%20Billie%20Eilish"
    assert (
        links["youtube"]
        == "https://www.youtube.com/results?search_query=bad%20guy%20Billie%20Eilish"
    )
    assert links["youtubeMusic"] == "https://music.youtube.com/search?q=bad%20guy%20Billie%20Eilish"


async def test_deezer_exact_via_isrc():
    d = _Dispatch(isrc=httpx.Response(200, json=_DEEZER_ISRC_OK))
    links = await _assembler(d).assemble("x", "y", "USXYZ")
    assert links["deezer"] == "https://www.deezer.com/track/111"
    # ISRC lookup hit; no Deezer search needed.
    assert any("/track/isrc:" in str(c.url) for c in d.calls)
    assert not any(c.url.host == "api.deezer.com" and c.url.path == "/search" for c in d.calls)


async def test_deezer_falls_back_to_search_without_isrc():
    d = _Dispatch(search=httpx.Response(200, json=_DEEZER_SEARCH_OK))
    links = await _assembler(d).assemble("x", "y")
    assert links["deezer"] == "https://www.deezer.com/track/222"


async def test_deezer_falls_back_to_deeplink_when_lookups_fail():
    # ISRC 404 + empty search → deep link.
    d = _Dispatch(
        isrc=httpx.Response(404), search=httpx.Response(200, json={"data": [], "total": 0})
    )
    links = await _assembler(d).assemble("solo song", "artist", "NOPE")
    assert links["deezer"] == "https://www.deezer.com/search/solo%20song%20artist"


async def test_deezer_error_body_falls_back():
    # Deezer signals quota as HTTP 200 + error body → treat as miss, deep link.
    d = _Dispatch(
        isrc=httpx.Response(200, json={"error": {"code": 4, "message": "quota"}}),
        search=httpx.Response(200, json={"error": {"code": 4, "message": "quota"}}),
    )
    links = await _assembler(d).assemble("x", "y", "I1")
    assert links["deezer"].startswith("https://www.deezer.com/search/")


async def test_apple_exact_via_itunes():
    links = await _assembler(_Dispatch(itunes=httpx.Response(200, json=_ITUNES_OK))).assemble(
        "x", "y"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/333"


async def test_apple_falls_back_to_deeplink():
    links = await _assembler(_Dispatch()).assemble("x", "y")
    assert links["appleMusic"] == "https://music.apple.com/search?term=x%20y"


# --------------------------------------------------------------------------- #
# Bandcamp (MYS-200) — search deep link only, no keyless lookup exists.
# --------------------------------------------------------------------------- #


async def test_bandcamp_is_a_search_deep_link():
    d = _Dispatch()
    links = await _assembler(d).assemble("bad guy", "Billie Eilish")
    assert (
        links["bandcamp"] == "https://bandcamp.com/search?q=bad%20guy%20Billie%20Eilish&item_type=t"
    )
    # Deep-link-only: no HTTP request to Bandcamp is ever made.
    assert not any(c.url.host.endswith("bandcamp.com") for c in d.calls)


async def test_bandcamp_deep_link_url_encodes_special_characters():
    links = await _assembler(_Dispatch()).assemble("Rock & Roll?", "AC/DC")
    # "&" and "?" must be percent-encoded so they don't corrupt the query string.
    assert (
        links["bandcamp"]
        == "https://bandcamp.com/search?q=Rock%20%26%20Roll%3F%20AC/DC&item_type=t"
    )


async def test_bandcamp_deep_link_without_artist():
    links = await _assembler(_Dispatch()).assemble("Untitled")
    assert links["bandcamp"] == "https://bandcamp.com/search?q=Untitled&item_type=t"


async def test_bandcamp_deep_link_survives_upstream_network_errors():
    # Bandcamp is built locally, so upstream failures can't take it out.
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    links = await _assembler(boom).assemble("x", "y", "I1")
    assert links["bandcamp"] == "https://bandcamp.com/search?q=x%20y&item_type=t"


async def test_network_error_falls_back_to_deeplinks():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    links = await _assembler(boom).assemble("x", "y", "I1")
    assert links["deezer"].startswith("https://www.deezer.com/search/")
    assert links["appleMusic"].startswith("https://music.apple.com/search?term=")


# --------------------------------------------------------------------------- #
# Relevance ranking (MYS-175) — best-match picking, not first-result.
# --------------------------------------------------------------------------- #


async def test_apple_picks_best_match_not_first_result():
    itunes_multi = {
        "resultCount": 2,
        "results": [
            {
                "trackName": "Totally Different Song",
                "artistName": "Someone Else",
                "trackViewUrl": "https://music.apple.com/track/wrong",
            },
            {
                "trackName": "Storm II",
                "artistName": "GENER8ION",
                "trackViewUrl": "https://music.apple.com/track/right",
            },
        ],
    }
    links = await _assembler(_Dispatch(itunes=httpx.Response(200, json=itunes_multi))).assemble(
        "Storm II", "GENER8ION"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/right"


async def test_deezer_search_fallback_picks_best_match():
    deezer_multi = {
        "data": [
            {
                "id": 1,
                "title": "Unrelated Track",
                "artist": {"name": "Nobody"},
                "link": "https://www.deezer.com/track/wrong",
            },
            {
                "id": 2,
                "title": "Storm II",
                "artist": {"name": "GENER8ION"},
                "link": "https://www.deezer.com/track/right",
            },
        ],
        "total": 2,
    }
    links = await _assembler(_Dispatch(search=httpx.Response(200, json=deezer_multi))).assemble(
        "Storm II", "GENER8ION"
    )
    assert links["deezer"] == "https://www.deezer.com/track/right"


async def test_youtube_exact_via_resolver():
    links = await _assembler(_Dispatch(), youtube_resolver=_FakeYouTubeResolver("abc123")).assemble(
        "x", "y"
    )
    assert links["youtube"] == "https://www.youtube.com/watch?v=abc123"
    # Same resolved video id, served through the Music app domain (MYS-175).
    assert links["youtubeMusic"] == "https://music.youtube.com/watch?v=abc123"


async def test_youtube_falls_back_to_deeplink_when_resolver_finds_nothing():
    links = await _assembler(_Dispatch(), youtube_resolver=_FakeYouTubeResolver(None)).assemble(
        "x", "y"
    )
    assert links["youtube"] == "https://www.youtube.com/results?search_query=x%20y"
    assert links["youtubeMusic"] == "https://music.youtube.com/search?q=x%20y"


async def test_youtube_falls_back_to_deeplink_when_no_resolver_configured():
    # No youtube_resolver injected at all (e.g. unconfigured API key) — behaves
    # exactly as before MYS-175, preserving the "no regression" requirement.
    links = await _assembler(_Dispatch()).assemble("x", "y")
    assert links["youtube"] == "https://www.youtube.com/results?search_query=x%20y"
    assert links["youtubeMusic"] == "https://music.youtube.com/search?q=x%20y"


async def test_assemble_resolves_youtube_video_id_only_once():
    # Callers that already resolved the video id (e.g. to persist it alongside
    # the links, MYS-175) can pass it through so assemble() doesn't spend a
    # second YouTube Data API call re-resolving the same thing.
    calls = 0

    class _CountingResolver:
        async def video_id_for(self, title, artist=None):
            nonlocal calls
            calls += 1
            return "should-not-be-used"

    links = await _assembler(_Dispatch(), youtube_resolver=_CountingResolver()).assemble(
        "x", "y", youtube_video_id="precomputed"
    )
    assert calls == 0
    assert links["youtube"] == "https://www.youtube.com/watch?v=precomputed"
    assert links["youtubeMusic"] == "https://music.youtube.com/watch?v=precomputed"


# --- Apple Music ISRC catalog matching (MYS-106) ------------------------------


async def test_apple_catalog_isrc_preferred_over_itunes():
    d = _Dispatch(
        catalog=httpx.Response(
            200,
            json={
                "data": [_catalog_song("Creep", "Radiohead", "https://music.apple.com/us/song/1")]
            },
        ),
        itunes=httpx.Response(200, json=_ITUNES_OK),
    )
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService()).assemble(
        "Creep", "Radiohead", "GBAYE9200070"
    )
    assert links["appleMusic"] == "https://music.apple.com/us/song/1"
    # The catalog hit short-circuits the keyless path entirely.
    assert "itunes.apple.com" not in d.hosts()


async def test_apple_catalog_sends_bearer_token_and_isrc_filter():
    d = _Dispatch(
        catalog=httpx.Response(
            200,
            json={
                "data": [_catalog_song("Creep", "Radiohead", "https://music.apple.com/us/song/1")]
            },
        )
    )
    await _assembler(d, apple_token_service=_FakeAppleTokenService("tok-123")).assemble(
        "Creep", "Radiohead", "GBAYE9200070"
    )
    call = next(c for c in d.calls if c.url.host == "api.music.apple.com")
    assert call.headers["Authorization"] == "Bearer tok-123"
    assert call.url.params["filter[isrc]"] == "GBAYE9200070"
    assert call.url.path == "/v1/catalog/us/songs"


async def test_apple_catalog_scores_multiple_songs_for_one_isrc():
    """One ISRC returning several songs is the norm, not an edge case.

    Verified against the live API: GBAYE9200070 (Radiohead - Creep) returns
    three. Duplicates can share an album name, so ranking is on title+artist.
    """
    d = _Dispatch(
        catalog=httpx.Response(
            200,
            json={
                "data": [
                    _catalog_song(
                        "Creep (Live)", "Radiohead", "https://music.apple.com/us/song/wrong", "EP"
                    ),
                    _catalog_song(
                        "Creep", "Radiohead", "https://music.apple.com/us/song/right", "Pablo Honey"
                    ),
                ]
            },
        )
    )
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService()).assemble(
        "Creep", "Radiohead", "GBAYE9200070"
    )
    assert links["appleMusic"] == "https://music.apple.com/us/song/right"


async def test_apple_falls_back_to_itunes_when_catalog_has_no_match():
    d = _Dispatch(
        catalog=httpx.Response(200, json={"data": []}),
        itunes=httpx.Response(200, json=_ITUNES_OK),
    )
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService()).assemble(
        "x", "y", "USXYZ1234567"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/333"


async def test_apple_falls_back_to_itunes_when_catalog_errors():
    d = _Dispatch(catalog=httpx.Response(500), itunes=httpx.Response(200, json=_ITUNES_OK))
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService()).assemble(
        "x", "y", "USXYZ1234567"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/333"


async def test_apple_skips_catalog_when_unconfigured():
    """No credentials: behave exactly as before MYS-106, with no wasted call."""
    d = _Dispatch(itunes=httpx.Response(200, json=_ITUNES_OK))
    links = await _assembler(d, apple_token_service=_UnconfiguredAppleTokenService()).assemble(
        "x", "y", "USXYZ1234567"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/333"
    assert "api.music.apple.com" not in d.hosts()


async def test_apple_skips_catalog_when_token_unusable():
    """Configured but unsignable (malformed key / mid-rotation) must not raise."""
    d = _Dispatch(itunes=httpx.Response(200, json=_ITUNES_OK))
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService(None)).assemble(
        "x", "y", "USXYZ1234567"
    )
    assert links["appleMusic"] == "https://music.apple.com/track/333"


async def test_apple_skips_catalog_without_isrc():
    """The catalog filter is ISRC-keyed; with no ISRC there's nothing to ask."""
    d = _Dispatch(itunes=httpx.Response(200, json=_ITUNES_OK))
    links = await _assembler(d, apple_token_service=_FakeAppleTokenService()).assemble("x", "y")
    assert links["appleMusic"] == "https://music.apple.com/track/333"
    assert "api.music.apple.com" not in d.hosts()
