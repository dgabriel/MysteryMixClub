"""Unit tests for app.services.odesli (MYS-44).

HTTP is mocked via httpx.MockTransport injected through the client factory, so
no network is touched. Covers the happy-path normalization (title/artist/
thumbnail/ISRC + platform filtering) and every error branch the router maps to
an HTTP status: invalid URL, not found, 429, timeout, upstream failure.
"""

import httpx
import pytest

from app.services.odesli import (
    InvalidSongURLError,
    OdesliClient,
    OdesliRateLimitError,
    OdesliTimeoutError,
    OdesliUnavailableError,
    SongNotFoundError,
)

# A representative Odesli /links response. Note tidal is present in
# linksByPlatform but must be filtered out — only the four product platforms
# are surfaced. ISRC lives only on the Spotify entity.
ODESLI_PAYLOAD = {
    "entityUniqueId": "ITUNES_SONG::1",
    "userCountry": "US",
    "pageUrl": "https://song.link/x",
    "entitiesByUniqueId": {
        "ITUNES_SONG::1": {
            "id": "1",
            "type": "song",
            "title": "bad guy",
            "artistName": "Billie Eilish",
            "thumbnailUrl": "https://img/itunes.jpg",
            "apiProvider": "itunes",
        },
        "SPOTIFY_SONG::2": {
            "id": "2",
            "type": "song",
            "title": "bad guy",
            "artistName": "Billie Eilish",
            "thumbnailUrl": "https://img/spotify.jpg",
            "isrc": "USUM71900764",
            "apiProvider": "spotify",
        },
    },
    "linksByPlatform": {
        "spotify": {"url": "https://open.spotify.com/track/2"},
        "appleMusic": {"url": "https://music.apple.com/x"},
        "youtube": {"url": "https://youtube.com/watch?v=z"},
        "deezer": {"url": "https://deezer.com/track/4"},
        "tidal": {"url": "https://tidal.com/x"},
    },
}


def _client(handler, *, api_key: str = "") -> OdesliClient:
    """OdesliClient whose every request is served by ``handler``."""

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return OdesliClient(api_key=api_key, client_factory=factory)


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=ODESLI_PAYLOAD)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_resolve_normalizes_core_fields():
    song = await _client(_ok).resolve("https://open.spotify.com/track/2")

    assert song.title == "bad guy"
    assert song.artist == "Billie Eilish"
    # Primary entity is the iTunes one (entityUniqueId), so its thumbnail wins.
    assert song.thumbnail_url == "https://img/itunes.jpg"


async def test_resolve_extracts_isrc_from_any_entity():
    song = await _client(_ok).resolve("https://open.spotify.com/track/2")
    assert song.isrc == "USUM71900764"


async def test_resolve_includes_only_known_platforms():
    song = await _client(_ok).resolve("https://open.spotify.com/track/2")

    assert set(song.platforms) == {"spotify", "youtube", "deezer", "appleMusic"}
    assert "tidal" not in song.platforms
    assert song.platforms["spotify"] == "https://open.spotify.com/track/2"


async def test_resolve_omits_platforms_without_links():
    payload = {
        "entityUniqueId": "SPOTIFY_SONG::2",
        "entitiesByUniqueId": {
            "SPOTIFY_SONG::2": {"title": "solo", "artistName": "x"},
        },
        "linksByPlatform": {"spotify": {"url": "https://open.spotify.com/track/2"}},
    }
    song = await _client(lambda r: httpx.Response(200, json=payload)).resolve(
        "https://open.spotify.com/track/2"
    )
    assert song.platforms == {"spotify": "https://open.spotify.com/track/2"}


async def test_api_key_is_sent_as_query_param_when_configured():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=ODESLI_PAYLOAD)

    await _client(handler, api_key="secret-key").resolve("https://open.spotify.com/track/2")
    assert seen.get("key") == "secret-key"
    assert seen.get("url") == "https://open.spotify.com/track/2"


async def test_api_key_absent_when_not_configured():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=ODESLI_PAYLOAD)

    await _client(handler).resolve("https://open.spotify.com/track/2")
    assert "key" not in seen


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://x", "spotify:track:2"])
async def test_invalid_url_raises_before_any_request(bad):
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("HTTP should not be called for an invalid URL")

    with pytest.raises(InvalidSongURLError):
        await _client(handler).resolve(bad)


@pytest.mark.parametrize("code", [400, 404])
async def test_not_found_status_raises_song_not_found(code):
    with pytest.raises(SongNotFoundError):
        await _client(lambda r: httpx.Response(code)).resolve("https://x/y")


async def test_empty_entities_raises_song_not_found():
    payload = {"entitiesByUniqueId": {}, "linksByPlatform": {}}
    with pytest.raises(SongNotFoundError):
        await _client(lambda r: httpx.Response(200, json=payload)).resolve("https://x/y")


async def test_rate_limit_raises():
    with pytest.raises(OdesliRateLimitError):
        await _client(lambda r: httpx.Response(429)).resolve("https://x/y")


async def test_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    with pytest.raises(OdesliTimeoutError):
        await _client(handler).resolve("https://x/y")


async def test_server_error_raises_unavailable():
    with pytest.raises(OdesliUnavailableError):
        await _client(lambda r: httpx.Response(503)).resolve("https://x/y")


async def test_transport_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(OdesliUnavailableError):
        await _client(handler).resolve("https://x/y")
