"""Unit tests for app.services.spotify_client (MYS-83).

HTTP is mocked via httpx.MockTransport injected through the client factory — no
network, no real credentials. Covers the auth flows (authorize URL, code
exchange, refresh, app-token caching), best-effort ISRC matching, the playlist
write calls, and error mapping (401 -> SpotifyAuthError, other non-2xx ->
SpotifyApiError).
"""

import httpx
import pytest

from app.services.spotify_client import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyClient,
)


def _client(handler, **kwargs) -> SpotifyClient:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    kwargs.setdefault("client_id", "cid")
    kwargs.setdefault("client_secret", "secret")
    kwargs.setdefault("redirect_uri", "http://localhost:8000/api/v1/spotify/callback")
    return SpotifyClient(client_factory=factory, **kwargs)


# --------------------------------------------------------------------------- #
# Config + authorize URL (pure)
# --------------------------------------------------------------------------- #


def test_is_configured_requires_all_three():
    assert _client(lambda r: httpx.Response(200)).is_configured is True
    assert SpotifyClient(client_id="", client_secret="s", redirect_uri="u").is_configured is False
    assert SpotifyClient(client_id="c", client_secret="", redirect_uri="u").is_configured is False
    assert SpotifyClient(client_id="c", client_secret="s", redirect_uri="").is_configured is False


def test_authorize_url_includes_required_params():
    url = _client(lambda r: httpx.Response(200)).authorize_url("state-123")
    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert "client_id=cid" in url
    assert "response_type=code" in url
    assert "state=state-123" in url
    assert "playlist-modify-public" in url
    assert "playlist-modify-private" in url


# --------------------------------------------------------------------------- #
# Token flows
# --------------------------------------------------------------------------- #


async def test_exchange_code_returns_tokens_and_sends_basic_auth():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        seen["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "at",
                "refresh_token": "rt",
                "scope": "playlist-modify-private",
                "expires_in": 3600,
            },
        )

    tokens = await _client(handler).exchange_code("the-code")
    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"
    assert tokens.scope == "playlist-modify-private"
    assert tokens.expires_in == 3600
    assert seen["auth"].startswith("Basic ")  # client creds, not in body
    assert "grant_type=authorization_code" in seen["body"]
    assert "code=the-code" in seen["body"]


async def test_exchange_code_invalid_grant_raises_auth_error():
    with pytest.raises(SpotifyAuthError):
        await _client(lambda r: httpx.Response(400, json={"error": "invalid_grant"})).exchange_code(
            "x"
        )


async def test_exchange_code_server_error_raises_api_error():
    with pytest.raises(SpotifyApiError):
        await _client(lambda r: httpx.Response(500)).exchange_code("x")


async def test_refresh_access_token_surfaces_rotated_refresh_token():
    payload = {"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600}
    tokens = await _client(lambda r: httpx.Response(200, json=payload)).refresh_access_token("rt1")
    assert tokens.access_token == "at2"
    assert tokens.refresh_token == "rt2"


async def test_app_access_token_is_cached():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"access_token": "app-tok", "expires_in": 3600})

    client = _client(handler)
    assert await client.app_access_token() == "app-tok"
    assert await client.app_access_token() == "app-tok"
    assert calls["n"] == 1  # second call served from cache


async def test_app_access_token_none_when_unconfigured():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no token request without client credentials")

    client = _client(handler, client_id="", client_secret="")
    assert await client.app_access_token() is None


# --------------------------------------------------------------------------- #
# Matching (best-effort: failures yield None, never raise)
# --------------------------------------------------------------------------- #


async def test_search_track_uri_by_isrc_happy():
    payload = {"tracks": {"items": [{"uri": "spotify:track:abc123"}]}}
    uri = await _client(lambda r: httpx.Response(200, json=payload)).search_track_uri_by_isrc(
        "USRC12345678", "tok"
    )
    assert uri == "spotify:track:abc123"


async def test_search_sends_isrc_query():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"tracks": {"items": [{"uri": "spotify:track:z"}]}})

    await _client(handler).search_track_uri_by_isrc("USRC99", "tok")
    assert seen["q"] == "isrc:USRC99"
    assert seen["type"] == "track"


async def test_search_returns_none_on_no_items():
    payload = {"tracks": {"items": []}}
    assert (
        await _client(lambda r: httpx.Response(200, json=payload)).search_track_uri_by_isrc(
            "I", "tok"
        )
        is None
    )


async def test_search_returns_none_without_token():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no search without an access token")

    assert await _client(handler).search_track_uri_by_isrc("I", "") is None


async def test_search_ignores_non_track_uri():
    payload = {"tracks": {"items": [{"uri": "spotify:album:nope"}]}}
    assert (
        await _client(lambda r: httpx.Response(200, json=payload)).search_track_uri_by_isrc(
            "I", "tok"
        )
        is None
    )


async def test_search_returns_none_on_error_status():
    assert await _client(lambda r: httpx.Response(429)).search_track_uri_by_isrc("I", "tok") is None


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


async def test_get_current_user_id_happy():
    uid = await _client(lambda r: httpx.Response(200, json={"id": "spuser"})).get_current_user_id(
        "tok"
    )
    assert uid == "spuser"


async def test_get_current_user_id_401_raises_auth_error():
    with pytest.raises(SpotifyAuthError):
        await _client(lambda r: httpx.Response(401)).get_current_user_id("tok")


async def test_create_playlist_uses_me_endpoint_and_returns_id_and_url():
    # The /users/{id}/playlists form was retired Feb 2026; must POST /me/playlists.
    payload = {
        "id": "pl123",
        "external_urls": {"spotify": "https://open.spotify.com/playlist/pl123"},
    }
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(201, json=payload)

    pid, url = await _client(handler).create_playlist("tok", "name", "desc")
    assert seen["path"] == "/v1/me/playlists"
    assert pid == "pl123"
    assert url == "https://open.spotify.com/playlist/pl123"


async def test_create_playlist_missing_id_raises_api_error():
    with pytest.raises(SpotifyApiError):
        await _client(lambda r: httpx.Response(201, json={})).create_playlist("tok", "n", "d")


async def test_add_tracks_chunks_at_100_via_items_endpoint():
    batches: list[int] = []
    paths: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        paths.add(request.url.path)
        batches.append(len(json.loads(request.content)["uris"]))
        return httpx.Response(201, json={"snapshot_id": "s"})

    uris = [f"spotify:track:{i}" for i in range(250)]
    await _client(handler).add_tracks("tok", "pl", uris)
    assert batches == [100, 100, 50]
    # The /tracks form was retired Feb 2026; must POST /playlists/{id}/items.
    assert paths == {"/v1/playlists/pl/items"}
