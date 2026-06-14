"""Unit tests for app.services.spotify_search (MYS-44).

HTTP is mocked via httpx.MockTransport. A single handler dispatches the
client-credentials token request and the search request by URL, so we exercise
the real two-step flow (auth then search), token caching, result normalization,
the too_many_results heuristic, and every error branch.
"""

import httpx
import pytest

from app.services.spotify_search import (
    SpotifyAuthError,
    SpotifyError,
    SpotifyRateLimitError,
    SpotifySearchClient,
    SpotifyTimeoutError,
    SpotifyUnavailableError,
)

TOKEN_HOST = "accounts.spotify.com"
SEARCH_HOST = "api.spotify.com"


def _track_item(idx: int) -> dict:
    return {
        "id": f"id{idx}",
        "name": f"Song {idx}",
        "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
        "album": {
            "name": "Album X",
            "images": [
                {"url": "https://img/large.jpg", "width": 640},
                {"url": "https://img/small.jpg", "width": 64},
            ],
        },
        "external_urls": {"spotify": f"https://open.spotify.com/track/id{idx}"},
    }


def _search_body(n_items: int, total: int) -> dict:
    return {"tracks": {"items": [_track_item(i) for i in range(n_items)], "total": total}}


class _Dispatcher:
    """Records requests and returns canned token + search responses."""

    def __init__(self, *, search_response: httpx.Response | None = None, token_status: int = 200):
        self.token_calls = 0
        self.search_calls: list[httpx.Request] = []
        self._search_response = search_response or httpx.Response(200, json=_search_body(2, 2))
        self._token_status = token_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            self.token_calls += 1
            if self._token_status != 200:
                return httpx.Response(self._token_status, json={"error": "bad"})
            return httpx.Response(
                200, json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
            )
        self.search_calls.append(request)
        return self._search_response


def _client(handler) -> SpotifySearchClient:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return SpotifySearchClient("cid", "secret", client_factory=factory)


# --------------------------------------------------------------------------- #
# Happy path + normalization
# --------------------------------------------------------------------------- #


async def test_search_normalizes_tracks():
    result = await _client(_Dispatcher()).search("bad guy")

    assert len(result.results) == 2
    track = result.results[0]
    assert track.id == "id0"
    assert track.title == "Song 0"
    assert track.artist == "Artist A, Artist B"
    assert track.album == "Album X"
    # Smallest image (last) is chosen as the thumbnail.
    assert track.thumbnail_url == "https://img/small.jpg"
    assert track.spotify_url == "https://open.spotify.com/track/id0"


async def test_search_skips_items_missing_id_or_name():
    body = {"tracks": {"items": [{"name": "no id"}, _track_item(1)], "total": 2}}
    dispatcher = _Dispatcher(search_response=httpx.Response(200, json=body))

    result = await _client(dispatcher).search("x")
    assert [t.id for t in result.results] == ["id1"]


# --------------------------------------------------------------------------- #
# too_many_results heuristic
# --------------------------------------------------------------------------- #


async def test_too_many_results_true_when_no_artist_and_total_over_limit():
    dispatcher = _Dispatcher(search_response=httpx.Response(200, json=_search_body(10, 250)))
    result = await _client(dispatcher).search("love")
    assert result.too_many_results is True
    assert len(result.results) == 10


async def test_too_many_results_false_when_artist_supplied():
    dispatcher = _Dispatcher(search_response=httpx.Response(200, json=_search_body(10, 250)))
    result = await _client(dispatcher).search("love", "Lana Del Rey")
    assert result.too_many_results is False


async def test_too_many_results_false_when_total_within_limit():
    dispatcher = _Dispatcher(search_response=httpx.Response(200, json=_search_body(3, 3)))
    result = await _client(dispatcher).search("very specific title")
    assert result.too_many_results is False


async def test_artist_filter_added_to_query():
    dispatcher = _Dispatcher()
    await _client(dispatcher).search("bad guy", "Billie Eilish")

    q = dict(dispatcher.search_calls[0].url.params)["q"]
    assert "track:bad guy" in q
    assert "artist:Billie Eilish" in q


# --------------------------------------------------------------------------- #
# Token caching
# --------------------------------------------------------------------------- #


async def test_token_is_cached_across_searches():
    dispatcher = _Dispatcher()
    client = _client(dispatcher)

    await client.search("a")
    await client.search("b")

    assert dispatcher.token_calls == 1
    assert len(dispatcher.search_calls) == 2


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_missing_credentials_raise_auth_error():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call expected without credentials")

    client = SpotifySearchClient(
        "", "", client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SpotifyAuthError):
        await client.search("x")


async def test_empty_title_raises_before_auth():
    dispatcher = _Dispatcher()
    with pytest.raises(SpotifyError):
        await _client(dispatcher).search("   ")
    assert dispatcher.token_calls == 0


async def test_rejected_credentials_raise_auth_error():
    with pytest.raises(SpotifyAuthError):
        await _client(_Dispatcher(token_status=401)).search("x")


async def test_search_429_raises_rate_limit():
    dispatcher = _Dispatcher(search_response=httpx.Response(429))
    with pytest.raises(SpotifyRateLimitError):
        await _client(dispatcher).search("x")


async def test_search_401_raises_auth_error():
    dispatcher = _Dispatcher(search_response=httpx.Response(401))
    with pytest.raises(SpotifyAuthError):
        await _client(dispatcher).search("x")


async def test_search_500_raises_unavailable():
    dispatcher = _Dispatcher(search_response=httpx.Response(503))
    with pytest.raises(SpotifyUnavailableError):
        await _client(dispatcher).search("x")


async def test_search_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == TOKEN_HOST:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SpotifyTimeoutError):
        await _client(handler).search("x")
