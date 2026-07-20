"""Endpoint tests for app.routers.songs (MYS-44, MYS-81).

The link-resolver and Deezer service dependencies are overridden with in-memory
fakes so we test the router's auth gate, request/response contract, and the
mapping from service errors to HTTP status codes — without any network or live
keys.
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
from app.services.link_resolver import (
    ResolverRateLimitError,
    ResolverTimeoutError,
    ResolverUnavailableError,
    SongIdentity,
    SongNotFoundError,
    get_link_resolver,
)
from app.services.song_links import get_link_assembler

RESOLVE_URL = "/api/v1/songs/resolve"
SEARCH_URL = "/api/v1/songs/search"

# What the (faked) link assembler returns for any song.
_ASSEMBLED = {
    "spotify": "https://open.spotify.com/search/bad%20guy",
    "appleMusic": "https://music.apple.com/track/9",
    "deezer": "https://www.deezer.com/track/2",
    "youtube": "https://music.youtube.com/search?q=bad%20guy",
}


class _FakeResolver:
    def __init__(self, *, result: SongIdentity | None = None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def resolve(self, url: str) -> SongIdentity:
        if self._error:
            raise self._error
        assert self._result is not None
        return self._result


class _FakeAssembler:
    def __init__(self, platforms: dict[str, str]):
        self._platforms = platforms

    async def assemble(
        self, title, artist=None, isrc=None, *, youtube_video_id=None, fuzzy=True
    ) -> dict[str, str]:
        # Return a copy: assemble_source_links mutates the dict (bandcamp override).
        return dict(self._platforms)


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
    user = User(email="dj@example.com", display_name="DJ")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _build_client(session_factory, *, resolver=None, deezer=None, assembler=None) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    if resolver is not None:
        app.dependency_overrides[get_link_resolver] = lambda: resolver
    if deezer is not None:
        app.dependency_overrides[get_deezer_client] = lambda: deezer
    if assembler is not None:
        app.dependency_overrides[get_link_assembler] = lambda: assembler

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_SONG = SongIdentity(
    title="bad guy",
    artist="Billie Eilish",
    album=None,
    thumbnail_url="https://img/x.jpg",
    isrc="USUM71900764",
)


# --------------------------------------------------------------------------- #
# Auth gate
# --------------------------------------------------------------------------- #


async def test_resolve_requires_auth(session_factory):
    async with _build_client(session_factory, resolver=_FakeResolver(result=_SONG)) as client:
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


async def test_resolve_by_pasted_url(session_factory, db_session):
    # Paste flow: the resolver identifies the song, the assembler builds links.
    user = await _seed_user(db_session)
    async with _build_client(
        session_factory, resolver=_FakeResolver(result=_SONG), assembler=_FakeAssembler(_ASSEMBLED)
    ) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={"url": "https://open.spotify.com/track/2"},
            headers=_auth_header(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "bad guy"
    assert body["isrc"] == "USUM71900764"
    assert set(body["platforms"]) == {"spotify", "appleMusic", "deezer", "youtube"}


async def test_resolve_by_identity_skips_resolver(session_factory, db_session):
    # Search-selected flow: identity provided, so the resolver is never called.
    user = await _seed_user(db_session)
    boom = _FakeResolver(
        error=AssertionError("resolver must not be called for an identity resolve")
    )
    async with _build_client(
        session_factory, resolver=boom, assembler=_FakeAssembler(_ASSEMBLED)
    ) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={"title": "bad guy", "artist": "Billie Eilish", "isrc": "USUM71900764"},
            headers=_auth_header(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "bad guy"
    assert set(body["platforms"]) == {"spotify", "appleMusic", "deezer", "youtube"}


async def test_resolve_without_url_or_title_is_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, resolver=_FakeResolver(result=_SONG)) as client:
        resp = await client.post(RESOLVE_URL, json={}, headers=_auth_header(user.id))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SongNotFoundError(), 404),
        (ResolverRateLimitError(), 429),
        (ResolverTimeoutError(), 504),
        (ResolverUnavailableError(), 502),
    ],
)
async def test_resolve_maps_service_errors(session_factory, db_session, error, expected):
    user = await _seed_user(db_session)
    async with _build_client(session_factory, resolver=_FakeResolver(error=error)) as client:
        resp = await client.post(
            RESOLVE_URL, json={"url": "https://x/y"}, headers=_auth_header(user.id)
        )
    assert resp.status_code == expected


# --------------------------------------------------------------------------- #
# POST /api/v1/songs/resolve — source-only opt-in (MYS-201)
# --------------------------------------------------------------------------- #

_SOURCE_SONG = SongIdentity(
    title="Bedroom Demo",
    artist="Cool Band",
    album=None,
    thumbnail_url="https://img/bc.jpg",
    isrc=None,
    source="bandcamp",
    source_key="bandcamp:coolband/bedroom-demo",
    source_url="https://coolband.bandcamp.com/track/bedroom-demo",
)


async def test_resolve_source_only_without_flag_is_404(session_factory, db_session):
    # Back-compat: an existing client (no allow_source_only) gets the same 404 a
    # catalog miss always produced, so nothing about the old contract changes.
    user = await _seed_user(db_session)
    async with _build_client(
        session_factory,
        resolver=_FakeResolver(result=_SOURCE_SONG),
        assembler=_FakeAssembler(_ASSEMBLED),
    ) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={"url": "https://coolband.bandcamp.com/track/bedroom-demo"},
            headers=_auth_header(user.id),
        )
    assert resp.status_code == 404, resp.text


async def test_resolve_source_only_with_flag_returns_source_metadata(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_client(
        session_factory,
        resolver=_FakeResolver(result=_SOURCE_SONG),
        assembler=_FakeAssembler(_ASSEMBLED),
    ) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={
                "url": "https://coolband.bandcamp.com/track/bedroom-demo",
                "allow_source_only": True,
            },
            headers=_auth_header(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["isrc"] is None
    assert body["source"] == "bandcamp"
    assert body["source_key"] == "bandcamp:coolband/bedroom-demo"
    assert body["source_url"] == "https://coolband.bandcamp.com/track/bedroom-demo"
    assert body["platforms"]  # cross-service links are assembled


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ResolverRateLimitError(), 429),
        (ResolverTimeoutError(), 504),
        (ResolverUnavailableError(), 502),
    ],
)
async def test_resolve_upstream_errors_map_even_with_source_flag(
    session_factory, db_session, error, expected
):
    # The flag only affects a genuine catalog miss; an upstream failure still maps
    # to the same status regardless of allow_source_only.
    user = await _seed_user(db_session)
    async with _build_client(session_factory, resolver=_FakeResolver(error=error)) as client:
        resp = await client.post(
            RESOLVE_URL,
            json={"url": "https://x/y", "allow_source_only": True},
            headers=_auth_header(user.id),
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
