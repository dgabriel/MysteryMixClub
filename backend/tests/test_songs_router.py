"""Endpoint tests for app.routers.songs (MYS-44).

The Odesli and Deezer service dependencies are overridden with in-memory fakes
so we test the router's auth gate, request/response contract, and the mapping
from service errors to HTTP status codes — without any network or live keys.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.user import User
from app.services.deezer_search import (
    DeezerRateLimitError,
    DeezerTimeoutError,
    DeezerUnavailableError,
    SongSearchResult,
    SongTrack,
    get_deezer_client,
)
from app.services.odesli import (
    OdesliRateLimitError,
    OdesliTimeoutError,
    OdesliUnavailableError,
    ResolvedSong,
    SongNotFoundError,
    get_odesli_client,
)

RESOLVE_URL = "/api/v1/songs/resolve"
SEARCH_URL = "/api/v1/songs/search"


class _FakeOdesli:
    def __init__(self, *, result: ResolvedSong | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def resolve(self, url: str) -> ResolvedSong:
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeDeezer:
    def __init__(self, *, result: SongSearchResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def search(self, title: str, artist: str | None = None) -> SongSearchResult:
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


async def _seed_user(db_session) -> User:
    user = User(email="dj@example.com", display_name="DJ", default_vibe_mode=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _build_client(session_factory, *, odesli=None, deezer=None) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    if odesli is not None:
        app.dependency_overrides[get_odesli_client] = lambda: odesli
    if deezer is not None:
        app.dependency_overrides[get_deezer_client] = lambda: deezer

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_SONG = ResolvedSong(
    title="bad guy",
    artist="Billie Eilish",
    album=None,
    thumbnail_url="https://img/x.jpg",
    isrc="USUM71900764",
    platforms={"spotify": "https://open.spotify.com/track/2", "youtube": "https://yt/z"},
)


# --------------------------------------------------------------------------- #
# Auth gate
# --------------------------------------------------------------------------- #


async def test_resolve_requires_auth(session_factory):
    async with _build_client(session_factory, odesli=_FakeOdesli(result=_SONG)) as client:
        resp = await client.post(RESOLVE_URL, json={"url": "https://x/y"})
    assert resp.status_code == 401


async def test_search_requires_auth(session_factory):
    async with _build_client(
        session_factory, deezer=_FakeDeezer(result=SongSearchResult(results=[]))
    ) as client:
        resp = await client.get(SEARCH_URL, params={"q": "x"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# POST /api/v1/songs/resolve
# --------------------------------------------------------------------------- #


async def test_resolve_happy_path(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, odesli=_FakeOdesli(result=_SONG)) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={"url": "https://open.spotify.com/track/2"},
            headers=_auth_header(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "bad guy"
    assert body["isrc"] == "USUM71900764"
    assert set(body["platforms"]) == {"spotify", "youtube"}


async def test_resolve_missing_url_is_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, odesli=_FakeOdesli(result=_SONG)) as client:
        resp = await client.post(RESOLVE_URL, json={}, headers=_auth_header(user.id))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SongNotFoundError(), 404),
        (OdesliRateLimitError(), 429),
        (OdesliTimeoutError(), 504),
        (OdesliUnavailableError(), 502),
    ],
)
async def test_resolve_maps_service_errors(session_factory, db_session, error, expected):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, odesli=_FakeOdesli(error=error)) as client:
        resp = await client.post(
            RESOLVE_URL, json={"url": "https://x/y"}, headers=_auth_header(user.id)
        )
    assert resp.status_code == expected


# --------------------------------------------------------------------------- #
# GET /api/v1/songs/search
# --------------------------------------------------------------------------- #


async def test_search_happy_path(session_factory, db_session):
    user = await _seed_user(db_session)
    result = SongSearchResult(
        results=[
            SongTrack(
                id="id0",
                title="Song 0",
                artist="Artist A",
                album="Album X",
                thumbnail_url="https://img/s.jpg",
                isrc="USUM71900764",
                resolve_url="https://www.deezer.com/track/id0",
            )
        ],
        too_many_results=False,
    )
    async with _build_client(session_factory, deezer=_FakeDeezer(result=result)) as client:
        resp = await client.get(SEARCH_URL, params={"q": "song"}, headers=_auth_header(user.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["too_many_results"] is False
    assert body["results"][0]["id"] == "id0"
    assert body["results"][0]["isrc"] == "USUM71900764"
    assert body["results"][0]["resolve_url"] == "https://www.deezer.com/track/id0"


async def test_search_surfaces_too_many_results(session_factory, db_session):
    user = await _seed_user(db_session)
    result = SongSearchResult(results=[], too_many_results=True)
    async with _build_client(session_factory, deezer=_FakeDeezer(result=result)) as client:
        resp = await client.get(SEARCH_URL, params={"q": "love"}, headers=_auth_header(user.id))
    assert resp.status_code == 200
    assert resp.json()["too_many_results"] is True


async def test_search_empty_q_is_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_client(
        session_factory, deezer=_FakeDeezer(result=SongSearchResult(results=[]))
    ) as client:
        resp = await client.get(SEARCH_URL, params={"q": ""}, headers=_auth_header(user.id))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DeezerRateLimitError(), 429),
        (DeezerTimeoutError(), 504),
        (DeezerUnavailableError(), 502),
    ],
)
async def test_search_maps_service_errors(session_factory, db_session, error, expected):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, deezer=_FakeDeezer(error=error)) as client:
        resp = await client.get(SEARCH_URL, params={"q": "x"}, headers=_auth_header(user.id))
    assert resp.status_code == expected
