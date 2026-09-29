"""Apple Music catalog search and lookup (MysteryMixClub-etjx, ADR 0039).

Developer-token-only reads: no Music User Token is ever sent. HTTP is mocked via
httpx.MockTransport. The point of the typed errors is that a caller can tell
"not in the catalog" (an empty list / None) from "Apple is broken" (a raise).
"""

import httpx
import pytest

from app.services.apple_music_client import (
    AppleMusicApiError,
    AppleMusicClient,
    AppleMusicError,
    AppleMusicRateLimitError,
    AppleMusicUnavailableError,
)


class _FakeTokenService:
    def __init__(self, configured: bool = True):
        self._configured = configured

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def get_developer_token(self) -> str:
        if not self._configured:
            from app.services.apple_music_token import AppleMusicTokenError

            raise AppleMusicTokenError("not configured")
        return "dev-token"


class _Dispatch:
    def __init__(self, response: httpx.Response | Exception):
        self._response = response
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _client(dispatch, *, configured=True, storefront="us") -> AppleMusicClient:
    return AppleMusicClient(
        _FakeTokenService(configured),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(dispatch), timeout=5.0
        ),
        storefront=storefront,
    )


def _row(song_id="1", name="Pepper", artist="Butthole Surfers", isrc="USCA29600428"):
    attrs = {"name": name, "artistName": artist}
    if isrc is not None:
        attrs["isrc"] = isrc
    return {"id": song_id, "type": "songs", "attributes": attrs}


def _search_body(*rows) -> dict:
    return {"results": {"songs": {"data": list(rows)}}}


# --------------------------------------------------------------------------- #
# search_songs
# --------------------------------------------------------------------------- #


async def test_search_parses_songs_and_uses_developer_token_only():
    dispatch = _Dispatch(httpx.Response(200, json=_search_body(_row("7", "Pepper"))))
    songs = await _client(dispatch).search_songs("Pepper Butthole Surfers")

    assert [(s.id, s.title, s.artist, s.isrc) for s in songs] == [
        ("7", "Pepper", "Butthole Surfers", "USCA29600428")
    ]
    request = dispatch.calls[0]
    assert request.headers["Authorization"] == "Bearer dev-token"
    assert "Music-User-Token" not in request.headers
    assert request.url.params["types"] == "songs"
    assert request.url.params["term"] == "Pepper Butthole Surfers"
    assert request.url.params["limit"] == "25"


async def test_search_targets_the_clients_storefront():
    dispatch = _Dispatch(httpx.Response(200, json=_search_body()))
    await _client(dispatch, storefront="gb").search_songs("x")
    assert dispatch.calls[0].url.path == "/v1/catalog/gb/search"


async def test_with_storefront_repins_search():
    dispatch = _Dispatch(httpx.Response(200, json=_search_body()))
    await _client(dispatch).with_storefront("jp").search_songs("x")
    assert dispatch.calls[0].url.path == "/v1/catalog/jp/search"


async def test_search_no_songs_key_is_an_empty_list_not_an_error():
    # Apple omits the "songs" group entirely when nothing matches.
    dispatch = _Dispatch(httpx.Response(200, json={"results": {}}))
    assert await _client(dispatch).search_songs("zzzz") == []


async def test_search_skips_unusable_rows_but_keeps_missing_isrc():
    rows = [_row("1", "Keep", isrc=None), {"id": "2"}, "junk", _row("3", "Also Keep")]
    dispatch = _Dispatch(httpx.Response(200, json=_search_body(*rows)))
    songs = await _client(dispatch).search_songs("x")
    assert [s.id for s in songs] == ["1", "3"]
    assert songs[0].isrc is None


async def test_search_rate_limit_raises_rate_limit_error():
    dispatch = _Dispatch(httpx.Response(429))
    with pytest.raises(AppleMusicRateLimitError):
        await _client(dispatch).search_songs("x")


@pytest.mark.parametrize("status", [401, 403, 500, 503])
async def test_search_token_rejection_and_5xx_raise_unavailable(status):
    dispatch = _Dispatch(httpx.Response(status))
    with pytest.raises(AppleMusicUnavailableError):
        await _client(dispatch).search_songs("x")


async def test_search_timeout_and_network_errors_raise_unavailable():
    with pytest.raises(AppleMusicUnavailableError):
        await _client(_Dispatch(httpx.ReadTimeout("slow"))).search_songs("x")
    with pytest.raises(AppleMusicUnavailableError):
        await _client(_Dispatch(httpx.ConnectError("down"))).search_songs("x")


async def test_search_bad_request_and_bad_body_raise_api_error():
    with pytest.raises(AppleMusicApiError):
        await _client(_Dispatch(httpx.Response(400))).search_songs("x")
    with pytest.raises(AppleMusicApiError):
        await _client(_Dispatch(httpx.Response(200, content=b"<html>"))).search_songs("x")
    with pytest.raises(AppleMusicApiError):
        await _client(_Dispatch(httpx.Response(200, json=["not", "a", "dict"]))).search_songs("x")
    with pytest.raises(AppleMusicApiError):
        # Search never legitimately 404s; treat it as broken, not as "no results".
        await _client(_Dispatch(httpx.Response(404))).search_songs("x")


async def test_search_unconfigured_raises_and_makes_no_request():
    dispatch = _Dispatch(httpx.Response(200, json=_search_body()))
    with pytest.raises(AppleMusicError):
        await _client(dispatch, configured=False).search_songs("x")
    assert dispatch.calls == []


# --------------------------------------------------------------------------- #
# catalog_song
# --------------------------------------------------------------------------- #


async def test_catalog_song_returns_the_song_in_the_storefront():
    dispatch = _Dispatch(httpx.Response(200, json={"data": [_row("724788539")]}))
    song = await _client(dispatch, storefront="gb").catalog_song("724788539")

    assert song is not None and song.isrc == "USCA29600428"
    assert dispatch.calls[0].url.path == "/v1/catalog/gb/songs/724788539"
    assert "Music-User-Token" not in dispatch.calls[0].headers


async def test_catalog_song_404_is_none_not_an_error():
    assert await _client(_Dispatch(httpx.Response(404))).catalog_song("123") is None


async def test_catalog_song_empty_data_is_none():
    assert (
        await _client(_Dispatch(httpx.Response(200, json={"data": []}))).catalog_song("1") is None
    )


@pytest.mark.parametrize("song_id", ["", "abc", "12/../../me", "1?x=y", "i.ABC123"])
async def test_catalog_song_non_numeric_id_never_reaches_a_url(song_id):
    dispatch = _Dispatch(httpx.Response(200, json={"data": [_row()]}))
    assert await _client(dispatch).catalog_song(song_id) is None
    assert dispatch.calls == []


async def test_catalog_song_failures_raise():
    with pytest.raises(AppleMusicRateLimitError):
        await _client(_Dispatch(httpx.Response(429))).catalog_song("1")
    with pytest.raises(AppleMusicUnavailableError):
        await _client(_Dispatch(httpx.Response(500))).catalog_song("1")
