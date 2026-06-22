"""Unit tests for app.services.link_resolver (MYS-81).

Every upstream (Deezer track + search, iTunes lookup, Spotify/YouTube oEmbed) is
mocked via httpx.MockTransport injected through the resolver's client_factory —
no network is touched. A single routing handler dispatches by host/path so the
Apple/Spotify/YouTube funnel-through-Deezer-search paths can be exercised
end-to-end. Covers each platform, URL cleaning, invalid-url / not-found, and the
rate-limit / timeout / unavailable error mapping.
"""

import httpx
import pytest

from app.services.link_resolver import (
    InvalidSongURLError,
    LinkResolver,
    ResolverRateLimitError,
    ResolverTimeoutError,
    ResolverUnavailableError,
    SongNotFoundError,
)

# Canonical Deezer search hit used by the Apple/Spotify/YouTube funnel.
_DEEZER_SEARCH_HIT = {
    "data": [
        {
            "id": 3156285,
            "title": "American Pie",
            "isrc": "USEM38600088",
            "artist": {"name": "Don McLean"},
            "album": {
                "title": "American Pie",
                "cover_medium": "https://img/deezer-med.jpg",
            },
            "link": "https://www.deezer.com/track/3156285",
        }
    ],
    "total": 1,
}

# Direct Deezer track lookup payload.
_DEEZER_TRACK = {
    "id": 3156285,
    "title": "American Pie",
    "isrc": "USEM38600088",
    "artist": {"name": "Don McLean"},
    "album": {
        "title": "American Pie",
        "cover_big": "https://img/deezer-big.jpg",
    },
}


def _router(*, search=None, track=None, itunes=None, spotify=None, youtube=None):
    """Build a MockTransport handler routing by host/path, with per-host overrides
    (a callable taking the request and returning an httpx.Response)."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "api.deezer.com" and path.startswith("/search"):
            return (search or (lambda r: httpx.Response(200, json=_DEEZER_SEARCH_HIT)))(request)
        if host == "api.deezer.com" and path.startswith("/track/"):
            return (track or (lambda r: httpx.Response(200, json=_DEEZER_TRACK)))(request)
        if host == "itunes.apple.com" and path.startswith("/lookup"):
            return (itunes or (lambda r: httpx.Response(200, json={"results": []})))(request)
        if host == "open.spotify.com" and path.startswith("/oembed"):
            return (spotify or (lambda r: httpx.Response(200, json={})))(request)
        if host == "www.youtube.com" and path.startswith("/oembed"):
            return (youtube or (lambda r: httpx.Response(200, json={})))(request)
        raise AssertionError(f"unexpected request to {host}{path}")

    return handler


def _resolver(handler) -> LinkResolver:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return LinkResolver(client_factory=factory)


# --------------------------------------------------------------------------- #
# Deezer — direct track lookup
# --------------------------------------------------------------------------- #


async def test_deezer_direct_track():
    song = await _resolver(_router()).resolve("https://www.deezer.com/track/3156285")
    assert song.title == "American Pie"
    assert song.artist == "Don McLean"
    assert song.isrc == "USEM38600088"
    assert song.album == "American Pie"
    assert song.thumbnail_url == "https://img/deezer-big.jpg"


async def test_deezer_localized_path_track():
    # Localized form /en/track/{id} must still parse the id.
    song = await _resolver(_router()).resolve("https://www.deezer.com/en/track/3156285")
    assert song.isrc == "USEM38600088"


async def test_deezer_non_track_url_is_invalid():
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve("https://www.deezer.com/album/123")


async def test_deezer_track_error_body_is_not_found():
    handler = _router(track=lambda r: httpx.Response(200, json={"error": {"code": 800}}))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://www.deezer.com/track/999")


# --------------------------------------------------------------------------- #
# Apple Music — iTunes lookup -> Deezer search
# --------------------------------------------------------------------------- #


async def test_apple_funnels_through_deezer_search():
    seen: dict[str, str] = {}

    def itunes(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={"results": [{"trackName": "American Pie", "artistName": "Don McLean"}]},
        )

    handler = _router(itunes=itunes)
    url = "https://music.apple.com/us/album/american-pie/1440834532?i=1440834619"
    song = await _resolver(handler).resolve(url)
    assert seen["id"] == "1440834619"  # the ?i= track id is looked up
    assert song.title == "American Pie"
    assert song.artist == "Don McLean"
    assert song.isrc == "USEM38600088"  # recovered from Deezer


async def test_apple_without_track_id_is_invalid():
    url = "https://music.apple.com/us/album/american-pie/1440834532"
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve(url)


async def test_apple_lookup_empty_is_not_found():
    handler = _router(itunes=lambda r: httpx.Response(200, json={"results": []}))
    url = "https://music.apple.com/us/album/x/1?i=2"
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve(url)


async def test_apple_version_suffix_is_cleaned_before_search():
    # iTunes returns "American Pie (Full Length Version)"; the suffix must be
    # stripped or the strict Deezer query misses the canonical track.
    seen: dict[str, str] = {}

    def itunes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"trackName": "American Pie (Full Length Version)", "artistName": "Don McLean"}
                ]
            },
        )

    handler = _router(search=_search_spy(seen), itunes=itunes)
    url = "https://music.apple.com/us/album/x/1?i=2"
    song = await _resolver(handler).resolve(url)
    assert 'track:"American Pie"' in seen["q"]
    assert 'artist:"Don McLean"' in seen["q"]
    assert song.isrc == "USEM38600088"


# --------------------------------------------------------------------------- #
# Spotify — oEmbed (title only) -> Deezer search
# --------------------------------------------------------------------------- #


async def test_spotify_funnels_through_deezer_search():
    handler = _router(spotify=lambda r: httpx.Response(200, json={"title": "American Pie"}))
    url = "https://open.spotify.com/track/3PfIrDoz19wz7qK7tYeu62"
    song = await _resolver(handler).resolve(url)
    assert song.title == "American Pie"
    assert song.isrc == "USEM38600088"


async def test_spotify_non_track_url_is_invalid():
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve("https://open.spotify.com/album/abc")


# --------------------------------------------------------------------------- #
# YouTube — oEmbed (noisy title) cleaned -> Deezer search
# --------------------------------------------------------------------------- #


def _search_spy(seen: dict[str, str]):
    def search(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_DEEZER_SEARCH_HIT)

    return search


@pytest.mark.parametrize(
    "raw_title",
    [
        "American Pie [HD]",
        "American Pie (Audio) (HD)",
        "American Pie | Official Music Video",
        "American Pie (Remastered 2022)",
        "American Pie (Official Video)",
    ],
)
async def test_youtube_bare_title_is_cleaned_and_searched(raw_title):
    # A bare song title with a non-Topic channel: the channel ("...VEVO") is an
    # unreliable artist hint and is ignored — search the cleaned title alone.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"title": raw_title, "author_name": "DonMcLeanVEVO"})

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")
    assert seen["q"] == "American Pie"  # cleaned, no bogus artist filter
    assert song.isrc == "USEM38600088"


async def test_youtube_artist_dash_title_is_split():
    # VEVO/official "Artist - Title (noise)" -> split into a strict artist/track
    # query; the channel name is ignored.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "title": "Don McLean - American Pie (Lyric Video)",
                "author_name": "DonMcLeanVEVO",
            },
        )

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")
    assert 'artist:"Don McLean"' in seen["q"]
    assert 'track:"American Pie"' in seen["q"]
    assert song.isrc == "USEM38600088"


async def test_youtube_topic_channel_supplies_artist():
    # YouTube Music auto-channel: bare title + "Artist - Topic" author is reliable.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"title": "American Pie", "author_name": "Don McLean - Topic"}
        )

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://music.youtube.com/watch?v=abc")
    assert 'artist:"Don McLean"' in seen["q"]
    assert 'track:"American Pie"' in seen["q"]
    assert song.isrc == "USEM38600088"


async def test_youtu_be_short_url_resolves():
    handler = _router(youtube=lambda r: httpx.Response(200, json={"title": "American Pie"}))
    song = await _resolver(handler).resolve("https://youtu.be/PRpiBpDy7MQ")
    assert song.isrc == "USEM38600088"


# --------------------------------------------------------------------------- #
# Dispatch + error mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://x", "spotify:track:2"])
async def test_invalid_url_raises_before_any_request(bad):
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP should be called for an invalid URL")

    with pytest.raises(InvalidSongURLError):
        await _resolver(handler).resolve(bad)


async def test_unknown_host_is_not_found():
    with pytest.raises(SongNotFoundError):
        await _resolver(_router()).resolve("https://example.com/track/1")


async def test_no_search_match_is_not_found():
    handler = _router(
        spotify=lambda r: httpx.Response(200, json={"title": "obscure"}),
        search=lambda r: httpx.Response(200, json={"data": [], "total": 0}),
    )
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://open.spotify.com/track/abc")


async def test_rate_limit_maps_to_resolver_rate_limit():
    handler = _router(track=lambda r: httpx.Response(429))
    with pytest.raises(ResolverRateLimitError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_timeout_maps_to_resolver_timeout():
    def track(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    handler = _router(track=track)
    with pytest.raises(ResolverTimeoutError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_server_error_maps_to_unavailable():
    handler = _router(track=lambda r: httpx.Response(503))
    with pytest.raises(ResolverUnavailableError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_transport_error_maps_to_unavailable():
    def track(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    handler = _router(track=track)
    with pytest.raises(ResolverUnavailableError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")
