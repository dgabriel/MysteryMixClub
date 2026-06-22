"""Route tests for the Spotify endpoints (MYS-83).

Pre-network gates (auth, membership, open_submission, not-connected) use the
shared ``client`` fixture, where the real Spotify client is unconfigured and
those handlers return before any HTTP call. The connect/status/create-playlist
happy paths use a local app wired with a ``FakeSpotifyClient`` so nothing touches
the network.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.spotify_connection import SpotifyConnection
from app.models.submission import Submission
from app.models.user import User
from app.services.spotify_client import SpotifyTokens, get_spotify_client
from app.services.spotify_token_crypto import encrypt_refresh_token
from app.services.youtube_resolver import get_youtube_resolver


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U", default_vibe_mode=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_round(db_session, organizer: User, *, state: str = "open_voting") -> Round:
    league = League(name="L", organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(league_id=league.id, round_number=1, theme="Late Summer", state=state)
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _seed_member(db_session, round_: Round, email: str) -> User:
    """A second league member (submissions are unique per round+user)."""
    user = await _seed_user(db_session, email)
    db_session.add(LeagueMember(league_id=round_.league_id, user_id=user.id))
    await db_session.commit()
    return user


async def _add_submission(db_session, round_id, user_id, *, isrc, title, spotify_track_uri=None):
    db_session.add(
        Submission(
            round_id=round_id,
            user_id=user_id,
            isrc=isrc,
            title=title,
            artist="A",
            platform_links={},
            spotify_track_uri=spotify_track_uri,
        )
    )
    await db_session.commit()


async def _connect(db_session, user_id) -> None:
    db_session.add(
        SpotifyConnection(
            user_id=user_id,
            spotify_user_id="spuser",
            refresh_token_encrypted=encrypt_refresh_token("rt"),
            scope="playlist-modify-private",
        )
    )
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _playlist_url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/spotify-playlist"


# --------------------------------------------------------------------------- #
# Fake client + local app fixture (no network)
# --------------------------------------------------------------------------- #


class FakeSpotifyClient:
    """Stands in for SpotifyClient. Resolves ISRCs from a fixed map and records
    the playlist it was asked to create."""

    def __init__(self, *, isrc_map=None, configured=True, existing_playlist_id=None):
        self._isrc_map = isrc_map or {}
        self._configured = configured
        # When set, find_playlist_id_by_name returns this id (reuse path).
        self._existing_playlist_id = existing_playlist_id
        self.created: dict | None = None
        self.added: list[str] = []
        self.replaced: dict | None = None
        self.looked_up_name: str | None = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    def authorize_url(self, state, scopes=None) -> str:
        return f"https://accounts.spotify.com/authorize?state={state}"

    async def app_access_token(self) -> str | None:
        return "app-tok" if self._configured else None

    async def search_track_uri_by_isrc(self, isrc, access_token) -> str | None:
        return self._isrc_map.get(isrc)

    async def refresh_access_token(self, refresh_token) -> SpotifyTokens:
        return SpotifyTokens(
            access_token="user-tok", refresh_token=None, scope=None, expires_in=3600
        )

    async def get_current_user_id(self, access_token) -> str:
        return "spuser"

    async def find_playlist_id_by_name(self, access_token, name) -> str | None:
        self.looked_up_name = name
        return self._existing_playlist_id

    async def create_playlist(self, access_token, name, description, *, public=False):
        self.created = {"name": name, "description": description}
        return "pl1", "https://open.spotify.com/playlist/pl1"

    async def add_tracks(self, access_token, playlist_id, uris) -> None:
        self.added.extend(uris)

    async def replace_tracks(self, access_token, playlist_id, uris) -> None:
        self.replaced = {"playlist_id": playlist_id, "uris": list(uris)}


@pytest_asyncio.fixture
async def fake_spotify() -> FakeSpotifyClient:
    return FakeSpotifyClient(isrc_map={"I-MATCH": "spotify:track:matched"})


def _client_with_spotify(session_factory, fake) -> AsyncClient:
    """An ASGI client whose Spotify dependency is `fake` (no network, no
    dependence on the ambient .env)."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_spotify_client] = lambda: fake
    app.dependency_overrides[get_youtube_resolver] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def spotify_client(session_factory, fake_spotify) -> AsyncGenerator[AsyncClient, None]:
    """Local app wired to a *configured* fake Spotify client."""
    async with _client_with_spotify(session_factory, fake_spotify) as ac:
        yield ac


@pytest_asyncio.fixture
async def unconfigured_client(session_factory) -> AsyncGenerator[AsyncClient, None]:
    """Local app wired to an *unconfigured* fake Spotify client — pins the
    'feature off' behaviour regardless of whether real creds sit in .env."""
    async with _client_with_spotify(session_factory, FakeSpotifyClient(configured=False)) as ac:
        yield ac


# --------------------------------------------------------------------------- #
# status / connect
# --------------------------------------------------------------------------- #


async def test_status_unconfigured_and_disconnected(unconfigured_client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    resp = await unconfigured_client.get("/api/v1/spotify/status", headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json() == {"configured": False, "connected": False}


async def test_status_connected(spotify_client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    await _connect(db_session, user.id)
    resp = await spotify_client.get("/api/v1/spotify/status", headers=_auth(user.id))
    assert resp.json() == {"configured": True, "connected": True}


async def test_connect_503_when_unconfigured(unconfigured_client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    resp = await unconfigured_client.get("/api/v1/spotify/connect", headers=_auth(user.id))
    assert resp.status_code == 503


async def test_connect_returns_authorize_url(spotify_client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    resp = await spotify_client.get("/api/v1/spotify/connect", headers=_auth(user.id))
    assert resp.status_code == 200
    assert resp.json()["authorize_url"].startswith("https://accounts.spotify.com/authorize")


# --------------------------------------------------------------------------- #
# create playlist — gates
# --------------------------------------------------------------------------- #


async def test_create_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.post(_playlist_url(round_.id))
    assert resp.status_code == 401


async def test_create_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.post(_playlist_url(round_.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_create_blocked_during_submission(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer, state="open_submission")
    resp = await client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_create_requires_connection(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409
    assert "connect" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# create playlist — happy path with the fake client
# --------------------------------------------------------------------------- #


async def test_create_builds_playlist_and_reports_unmatched(
    spotify_client, db_session, fake_spotify
):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    other = await _seed_member(db_session, round_, "m2@example.com")
    # One track resolves via the fake's isrc_map; one does not.
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    await _add_submission(db_session, round_.id, other.id, isrc="I-MISS", title="miss")

    resp = await spotify_client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl1"
    assert body["track_count"] == 1
    assert body["total_count"] == 2
    assert len(body["unmatched"]) == 1
    assert body["unmatched"][0]["title"] == "miss"
    # The matched uri was added; the title carries league name + theme (MYS-86),
    # and we looked it up first (reuse check, MYS-87).
    assert fake_spotify.added == ["spotify:track:matched"]
    assert fake_spotify.created["name"] == "MysteryMixClub: L, Late Summer"
    assert fake_spotify.looked_up_name == "MysteryMixClub: L, Late Summer"


async def test_create_caches_resolved_uri_on_submission(spotify_client, db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    resp = await spotify_client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200

    # The resolved uri should now be cached on the submission row.
    from sqlalchemy import select

    sub = await db_session.scalar(select(Submission).where(Submission.round_id == round_.id))
    assert sub.spotify_track_uri == "spotify:track:matched"


async def test_create_no_matches_returns_no_playlist(spotify_client, db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MISS", title="miss")

    resp = await spotify_client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200
    body = resp.json()
    assert body["playlist_url"] is None
    assert body["track_count"] == 0
    assert fake_spotify.created is None  # no empty playlist created


async def test_create_reuses_existing_playlist_instead_of_duplicating(session_factory, db_session):
    # When a same-named playlist already exists, reuse it (replace tracks) rather
    # than creating a duplicate (MYS-87).
    fake = FakeSpotifyClient(
        isrc_map={"I-MATCH": "spotify:track:matched"}, existing_playlist_id="pl-existing"
    )
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert fake.created is None  # did NOT create a new playlist
    assert fake.replaced == {"playlist_id": "pl-existing", "uris": ["spotify:track:matched"]}
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl-existing"
    assert body["track_count"] == 1
