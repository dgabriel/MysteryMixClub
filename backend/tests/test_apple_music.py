"""Apple Music client + route tests (MYS-108).

HTTP is mocked via httpx.MockTransport — nothing touches Apple. Covers the
client's catalog resolution and create-then-add, and the three routes:
developer token, read the caller's playlist, generate it.

Per-player is the whole point here (MYS-107): playlists are keyed by
(mix, user), so one member must never see another's link.
"""

import json
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.apple_mix_playlist import AppleMixPlaylist
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.services.apple_playlist_generation import revised_playlist_name
from app.services.apple_music_client import (
    LIBRARY_URL,
    AppleMusicApiError,
    AppleMusicAuthError,
    AppleMusicClient,
    get_apple_music_client,
    library_playlist_url,
)

CATALOG_HOST = "api.music.apple.com"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeTokenService:
    def __init__(self, configured: bool = True):
        self._configured = configured

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def get_developer_token(self) -> str:
        return "dev-token"


def _song(song_id: str, name: str, artist: str = "Radiohead"):
    return {"id": song_id, "attributes": {"name": name, "artistName": artist}}


class _Dispatch:
    """Routes Apple API paths to canned responses and records every request."""

    def __init__(self, *, catalog=None, create=None, add=None, storefront=None):
        self.catalog = catalog
        self.create = create
        self.add = add
        self.storefront = storefront
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if path.endswith("/me/storefront"):
            return self.storefront or httpx.Response(200, json={"data": [{"id": "us"}]})
        if "/catalog/" in path and path.endswith("/songs"):
            return self.catalog or httpx.Response(200, json={"data": []})
        if path.endswith("/tracks"):
            return self.add or httpx.Response(201, json={})
        if path.endswith("/me/library/playlists"):
            return self.create or httpx.Response(201, json={"data": [{"id": "p.NEW"}]})
        return httpx.Response(404)

    def paths(self) -> list[str]:
        return [c.url.path for c in self.calls]


def _client(dispatch, *, configured=True, storefront="us") -> AppleMusicClient:
    return AppleMusicClient(
        _FakeTokenService(configured),
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(dispatch), timeout=5.0
        ),
        storefront=storefront,
    )


# --------------------------------------------------------------------------- #
# Client — catalog resolution
# --------------------------------------------------------------------------- #


async def test_catalog_song_id_for_isrc_returns_id():
    d = _Dispatch(catalog=httpx.Response(200, json={"data": [_song("123", "Creep")]}))
    assert await _client(d).catalog_song_id_for_isrc("GBAYE9200070", "Creep", "Radiohead") == "123"


async def test_catalog_song_id_scores_multiple_results():
    """One ISRC → several songs is the norm; pick by title/artist, not order."""
    d = _Dispatch(
        catalog=httpx.Response(
            200, json={"data": [_song("wrong", "Creep (Live)"), _song("right", "Creep")]}
        )
    )
    assert await _client(d).catalog_song_id_for_isrc("I1", "Creep", "Radiohead") == "right"


async def test_catalog_song_id_uses_configured_storefront():
    d = _Dispatch(catalog=httpx.Response(200, json={"data": [_song("1", "x")]}))
    await _client(d, storefront="gb").catalog_song_id_for_isrc("I1", "x", "y")
    assert "/v1/catalog/gb/songs" in d.paths()


async def test_catalog_song_id_none_on_empty_or_error():
    assert await _client(_Dispatch()).catalog_song_id_for_isrc("I1", "x", "y") is None
    d = _Dispatch(catalog=httpx.Response(500))
    assert await _client(d).catalog_song_id_for_isrc("I1", "x", "y") is None


async def test_storefront_for_user_reads_apple_then_falls_back():
    d = _Dispatch(storefront=httpx.Response(200, json={"data": [{"id": "gb"}]}))
    assert await _client(d).storefront_for_user("mut") == "gb"
    bad = _Dispatch(storefront=httpx.Response(500))
    assert await _client(bad).storefront_for_user("mut") == "us"


# --------------------------------------------------------------------------- #
# Client — playlist creation
# --------------------------------------------------------------------------- #


async def test_create_library_playlist_sends_both_tokens():
    d = _Dispatch()
    await _client(d).create_library_playlist("mut-abc", "Name", "Desc", ["1"])
    create = next(c for c in d.calls if c.url.path.endswith("/me/library/playlists"))
    assert create.headers["Authorization"] == "Bearer dev-token"
    assert create.headers["Music-User-Token"] == "mut-abc"


async def test_create_library_playlist_returns_id():
    d = _Dispatch(create=httpx.Response(201, json={"data": [{"id": "p.XYZ"}]}))
    assert await _client(d).create_library_playlist("m", "N", "D", ["1"]) == "p.XYZ"


async def test_create_library_playlist_chunks_beyond_100_tracks():
    """Apple caps tracks per request; the remainder must be appended, not dropped."""
    d = _Dispatch()
    await _client(d).create_library_playlist("m", "N", "D", [str(i) for i in range(250)])

    create = next(c for c in d.calls if c.url.path.endswith("/me/library/playlists"))
    sent_with_create = json.loads(create.read())["relationships"]["tracks"]["data"]
    adds = [c for c in d.calls if c.url.path.endswith("/tracks")]
    appended = [tid for c in adds for tid in json.loads(c.read())["data"]]

    assert len(sent_with_create) == 100
    assert len(appended) == 150
    # Every track lands exactly once, in order — the add endpoint can't reorder.
    all_ids = [t["id"] for t in sent_with_create] + [t["id"] for t in appended]
    assert all_ids == [str(i) for i in range(250)]


async def test_create_library_playlist_auth_error_on_401():
    d = _Dispatch(create=httpx.Response(401, json={}))
    with pytest.raises(AppleMusicAuthError):
        await _client(d).create_library_playlist("m", "N", "D", ["1"])


async def test_create_library_playlist_api_error_on_500():
    d = _Dispatch(create=httpx.Response(500, json={}))
    with pytest.raises(AppleMusicApiError):
        await _client(d).create_library_playlist("m", "N", "D", ["1"])


async def test_create_library_playlist_api_error_on_unreadable_body():
    d = _Dispatch(create=httpx.Response(201, json={"data": []}))
    with pytest.raises(AppleMusicApiError):
        await _client(d).create_library_playlist("m", "N", "D", ["1"])


def test_library_url_points_at_the_library_not_the_playlist():
    """iOS dead-ends on a library-playlist deep link, so we link the Library
    itself and name the playlist instead (MYS-190)."""
    assert LIBRARY_URL == "https://music.apple.com/library"


def test_library_playlist_url_addresses_the_exact_playlist():
    """Desktop-only direct link (MYS-214) — the web player resolves this path."""
    assert library_playlist_url("p.ABC123") == "https://music.apple.com/library/playlist/p.ABC123"


# --------------------------------------------------------------------------- #
# Route fixtures
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_mix(db_session, organizer: User) -> Mix:
    club = Club(name="L", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    mix_ = Mix(club_id=club.id, mix_number=1, theme="Late Summer", state="open_voting")
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _add_submission(db_session, mix_id, user_id, *, isrc, title, source_key=None):
    db_session.add(
        Submission(
            mix_id=mix_id,
            user_id=user_id,
            isrc=isrc,
            source_key=source_key,
            title=title,
            artist="A",
            platform_links={},
        )
    )
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(mix_id) -> str:
    return f"/api/v1/mixes/{mix_id}/apple-playlist"


@pytest_asyncio.fixture
async def apple_app(db_session, request) -> AsyncGenerator[AsyncClient, None]:
    """App wired with a mock-transport Apple client. Parametrize the dispatch via
    ``@pytest.mark.parametrize('apple_app', [dispatch], indirect=True)``."""
    dispatch = getattr(request, "param", None) or _Dispatch()
    app = create_app()

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_apple_music_client] = lambda: _client(dispatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.dispatch = dispatch  # type: ignore[attr-defined]
        yield ac


# --------------------------------------------------------------------------- #
# Routes — developer token
# --------------------------------------------------------------------------- #


async def test_developer_token_requires_auth(apple_app):
    assert (await apple_app.get("/api/v1/apple-music/developer-token")).status_code == 401


async def test_developer_token_returned_when_configured(apple_app, db_session):
    user = await _seed_user(db_session, "a@example.com")
    r = await apple_app.get("/api/v1/apple-music/developer-token", headers=_auth(user.id))
    assert r.status_code == 200
    assert r.json()["token"] == "dev-token"


async def test_developer_token_null_when_unconfigured(db_session):
    """Unconfigured is a normal state, not an error — the client hides Apple."""
    app = create_app()

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_apple_music_client] = lambda: _client(
        _Dispatch(), configured=False
    )
    user = await _seed_user(db_session, "b@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/apple-music/developer-token", headers=_auth(user.id))
    assert r.status_code == 200
    assert r.json()["token"] is None


# --------------------------------------------------------------------------- #
# Routes — read the caller's playlist
# --------------------------------------------------------------------------- #


async def test_get_playlist_null_when_none_generated(apple_app, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    r = await apple_app.get(_url(mix_.id), headers=_auth(organizer.id))
    assert r.status_code == 200
    assert r.json()["playlist_url"] is None
    assert r.json()["direct_playlist_url"] is None


async def test_get_playlist_returns_own_link(apple_app, db_session):
    organizer = await _seed_user(db_session, "o2@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    db_session.add(
        AppleMixPlaylist(
            mix_id=mix_.id,
            user_id=organizer.id,
            playlist_id="p.MINE",
            playlist_name="Mix: Mix 1",
        )
    )
    await db_session.commit()
    r = await apple_app.get(_url(mix_.id), headers=_auth(organizer.id))
    assert r.json()["playlist_url"] == "https://music.apple.com/library"
    assert r.json()["direct_playlist_url"] == "https://music.apple.com/library/playlist/p.MINE"
    assert r.json()["playlist_name"] == "Mix: Mix 1"


async def test_get_playlist_is_per_user_not_shared(apple_app, db_session):
    """Another member's playlist must never leak — the link is personal."""
    organizer = await _seed_user(db_session, "o3@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    other = await _seed_user(db_session, "m3@example.com")
    db_session.add(ClubMember(club_id=mix_.club_id, user_id=other.id))
    db_session.add(AppleMixPlaylist(mix_id=mix_.id, user_id=organizer.id, playlist_id="p.ORG"))
    await db_session.commit()
    r = await apple_app.get(_url(mix_.id), headers=_auth(other.id))
    assert r.json()["playlist_url"] is None
    assert r.json()["direct_playlist_url"] is None


async def test_get_playlist_forbidden_for_non_member(apple_app, db_session):
    organizer = await _seed_user(db_session, "o4@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    outsider = await _seed_user(db_session, "x4@example.com")
    r = await apple_app.get(_url(mix_.id), headers=_auth(outsider.id))
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# Routes — generate
# --------------------------------------------------------------------------- #


async def test_generate_creates_playlist_and_persists_it(apple_app, db_session):
    organizer = await _seed_user(db_session, "o5@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})

    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["playlist_url"] == "https://music.apple.com/library"
    assert body["direct_playlist_url"].startswith("https://music.apple.com/library/playlist/")
    assert body["playlist_name"]
    assert body["track_count"] == 1
    assert body["total_count"] == 1
    assert body["unmatched"] == []

    # Persisted, so the link survives a reload.
    follow_up = await apple_app.get(_url(mix_.id), headers=_auth(organizer.id))
    assert follow_up.json()["playlist_url"] == body["playlist_url"]
    assert follow_up.json()["direct_playlist_url"] == body["direct_playlist_url"]


async def test_generate_reports_unmatched_tracks(apple_app, db_session):
    """No catalog match is expected, not fatal — MYS-166 tracks have no ISRC."""
    organizer = await _seed_user(db_session, "o6@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Obscure")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": []})

    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["track_count"] == 0
    assert body["total_count"] == 1
    assert [u["title"] for u in body["unmatched"]] == ["Obscure"]
    # An ISRC-backed track Apple's catalog just doesn't carry (MYS-201 Phase 2).
    assert body["unmatched"][0]["reason"] == "no_catalog_match"
    # No source_key on a catalog track — nothing to link out to (MYS-201).
    assert body["unmatched"][0]["source"] is None
    assert body["unmatched"][0]["source_url"] is None


async def test_generate_skips_source_only_track_without_catalog_lookup(apple_app, db_session):
    # A source-only submission has no ISRC to resolve against Apple's catalog, so
    # it goes unmatched and Apple's catalog is never queried for it (MYS-201).
    organizer = await _seed_user(db_session, "src@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(
        db_session,
        mix_.id,
        organizer.id,
        isrc=None,
        source_key="bandcamp:coolband/demo",
        title="bandcamp only",
    )

    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["track_count"] == 0
    assert body["total_count"] == 1
    assert [u["title"] for u in body["unmatched"]] == ["bandcamp only"]
    # Reported as source-only, distinct from a catalog miss (MYS-201 Phase 2).
    assert body["unmatched"][0]["reason"] == "source_only"
    # Carries the Bandcamp page so the frontend can link out to it (MYS-201).
    assert body["unmatched"][0]["source"] == "bandcamp"
    assert body["unmatched"][0]["source_url"] == "https://coolband.bandcamp.com/track/demo"
    # No catalog /songs lookup was attempted for the source-only track.
    assert not any("/catalog/" in p and p.endswith("/songs") for p in apple_app.dispatch.paths())


async def test_generate_401_when_apple_rejects_user_token(apple_app, db_session):
    """Expired/revoked MUT → 401 so the client re-runs the MusicKit popup."""
    organizer = await _seed_user(db_session, "o7@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})
    apple_app.dispatch.create = httpx.Response(401, json={})

    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "stale"}, headers=_auth(organizer.id)
    )
    assert r.status_code == 401
    assert "reconnect" in r.json()["detail"]


async def test_generate_502_on_apple_failure(apple_app, db_session):
    organizer = await _seed_user(db_session, "o8@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})
    apple_app.dispatch.create = httpx.Response(500, json={})

    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )
    assert r.status_code == 502


async def test_generate_forbidden_for_non_member(apple_app, db_session):
    organizer = await _seed_user(db_session, "o9@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    outsider = await _seed_user(db_session, "x9@example.com")
    r = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(outsider.id)
    )
    assert r.status_code == 403


async def test_generate_503_when_unconfigured(db_session):
    app = create_app()

    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_apple_music_client] = lambda: _client(
        _Dispatch(), configured=False
    )
    organizer = await _seed_user(db_session, "o10@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
        )
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# Revision naming after a mix is reopened (MYS-108)
# --------------------------------------------------------------------------- #


def test_revised_playlist_name_uses_local_time():
    when = datetime(2026, 7, 18, 22, 5, tzinfo=timezone.utc)
    # UTC-4: 22:05Z is 18:05 locally.
    assert revised_playlist_name("Mix: R1", when, -240) == "Mix: R1 [revised on 18:05]"


def test_revised_playlist_name_falls_back_to_utc():
    when = datetime(2026, 7, 18, 22, 5, tzinfo=timezone.utc)
    assert revised_playlist_name("Mix: R1", when, None) == "Mix: R1 [revised on 22:05]"


def test_revised_playlist_name_wraps_across_midnight():
    """UTC+14 pushes 22:05Z into the next day — the clock must wrap, not overflow."""
    when = datetime(2026, 7, 18, 22, 5, tzinfo=timezone.utc)
    assert revised_playlist_name("Mix: R1", when, 840) == "Mix: R1 [revised on 12:05]"


async def test_first_generation_has_no_revision_suffix(apple_app, db_session):
    organizer = await _seed_user(db_session, "rev1@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})

    await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )

    create = next(c for c in apple_app.dispatch.calls if c.url.path.endswith("/library/playlists"))
    assert "[revised on" not in json.loads(create.read())["attributes"]["name"]


async def test_rebuild_after_supersede_is_named_as_a_revision(apple_app, db_session):
    """The whole point: Apple allows two same-named playlists, so say which is new."""
    organizer = await _seed_user(db_session, "rev2@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    # Captured before the expire_all() below — reading mix_.id afterwards
    # triggers a lazy refresh and raises MissingGreenlet.
    mix_id = mix_.id
    await _add_submission(db_session, mix_id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})

    # A superseded playlist from before the mix was reopened.
    db_session.add(
        AppleMixPlaylist(
            mix_id=mix_id,
            user_id=organizer.id,
            playlist_id="p.OLD",
            superseded_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    # It's hidden from the mix page, so the build CTA is offered again.
    assert (await apple_app.get(_url(mix_id), headers=_auth(organizer.id))).json()[
        "playlist_url"
    ] is None

    r = await apple_app.post(
        _url(mix_id),
        json={"music_user_token": "mut", "tz_offset_minutes": 0},
        headers=_auth(organizer.id),
    )
    assert r.status_code == 200, r.text

    create = next(c for c in apple_app.dispatch.calls if c.url.path.endswith("/library/playlists"))
    assert "[revised on" in json.loads(create.read())["attributes"]["name"]

    # One row per (mix, user): the rebuild takes over rather than piling up.
    db_session.expire_all()
    rows = (
        await db_session.scalars(select(AppleMixPlaylist).where(AppleMixPlaylist.mix_id == mix_id))
    ).all()
    assert len(rows) == 1
    assert rows[0].playlist_id == "p.NEW"
    assert rows[0].superseded_at is None


async def test_rejects_absurd_tz_offset(apple_app, db_session):
    organizer = await _seed_user(db_session, "rev3@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    r = await apple_app.post(
        _url(mix_.id),
        json={"music_user_token": "mut", "tz_offset_minutes": 5000},
        headers=_auth(organizer.id),
    )
    assert r.status_code == 422


async def test_get_playlist_name_null_for_pre_mys190_rows(apple_app, db_session):
    """Rows created before names were recorded still return a usable link."""
    organizer = await _seed_user(db_session, "legacy@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    db_session.add(AppleMixPlaylist(mix_id=mix_.id, user_id=organizer.id, playlist_id="p.OLD"))
    await db_session.commit()

    r = await apple_app.get(_url(mix_.id), headers=_auth(organizer.id))
    assert r.json()["playlist_url"] == "https://music.apple.com/library"
    assert r.json()["direct_playlist_url"] == "https://music.apple.com/library/playlist/p.OLD"
    assert r.json()["playlist_name"] is None


async def test_generated_name_is_persisted_for_later_visits(apple_app, db_session):
    organizer = await _seed_user(db_session, "persist@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I1", title="Creep")
    apple_app.dispatch.catalog = httpx.Response(200, json={"data": [_song("s1", "Creep")]})

    created = await apple_app.post(
        _url(mix_.id), json={"music_user_token": "mut"}, headers=_auth(organizer.id)
    )
    name = created.json()["playlist_name"]
    assert name

    # Same name on a later read — it's stored, not recomputed (a revision's
    # "[revised on HH:MM]" suffix could never be reconstructed).
    follow_up = await apple_app.get(_url(mix_.id), headers=_auth(organizer.id))
    assert follow_up.json()["playlist_name"] == name
