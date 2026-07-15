"""Unit tests for app.services.song_links (MYS-52).

HTTP is mocked via httpx.MockTransport. Covers the assembled platform map:
Spotify/YouTube deep links (always), Deezer exact via ISRC then search then
deep-link fallback, Apple exact via iTunes then deep-link fallback, and
best-effort behaviour when an upstream errors.
"""

import httpx

from app.services.song_links import SongLinkAssembler

_DEEZER_ISRC_OK = {"id": 1, "link": "https://www.deezer.com/track/111", "isrc": "USXYZ"}
_DEEZER_SEARCH_OK = {"data": [{"id": 2, "link": "https://www.deezer.com/track/222"}], "total": 1}
_ITUNES_OK = {"resultCount": 1, "results": [{"trackViewUrl": "https://music.apple.com/track/333"}]}


class _Dispatch:
    def __init__(self, *, isrc=None, search=None, itunes=None):
        self.isrc = isrc
        self.search = search
        self.itunes = itunes
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.deezer.com" and path.startswith("/track/isrc:"):
            return self.isrc or httpx.Response(404)
        if host == "api.deezer.com" and path == "/search":
            return self.search or httpx.Response(200, json={"data": [], "total": 0})
        if host == "itunes.apple.com":
            return self.itunes or httpx.Response(200, json={"resultCount": 0, "results": []})
        return httpx.Response(404)


def _assembler(dispatch, *, youtube_resolver=None) -> SongLinkAssembler:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)

    return SongLinkAssembler(client_factory=factory, youtube_resolver=youtube_resolver)


class _FakeYouTubeResolver:
    """Stub matching YouTubeResolver's interface for injection into the assembler."""

    def __init__(self, video_id: str | None):
        self._video_id = video_id

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        return self._video_id


async def test_assemble_returns_all_five_platforms():
    a = _assembler(
        _Dispatch(
            isrc=httpx.Response(200, json=_DEEZER_ISRC_OK),
            itunes=httpx.Response(200, json=_ITUNES_OK),
        )
    )
    links = await a.assemble("Blinding Lights", "The Weeknd", "USUG11904206")
    assert set(links) == {"spotify", "appleMusic", "deezer", "youtube", "youtubeMusic"}


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
