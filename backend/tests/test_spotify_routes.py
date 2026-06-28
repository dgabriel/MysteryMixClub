"""Route tests for the Spotify endpoints (MYS-83).

Pre-network gates (auth, membership, open_submission, not-connected) use the
shared ``client`` fixture, where the real Spotify client is unconfigured and
those handlers return before any HTTP call. The connect/status/create-playlist
happy paths use a local app wired with a ``FakeSpotifyClient`` so nothing touches
the network.
"""

import random
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_oauth_state
from app.db.session import get_db
from app.main import create_app
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.spotify_connection import SpotifyConnection
from app.models.spotify_round_playlist import SpotifyRoundPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.services.spotify_client import SpotifyNotFoundError, SpotifyTokens, get_spotify_client
from app.services.spotify_token_crypto import encrypt_refresh_token
from app.services.youtube_resolver import get_youtube_resolver


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
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
    the playlist operations it was asked to perform."""

    def __init__(self, *, isrc_map=None, configured=True, replace_raises_not_found=False):
        self._isrc_map = isrc_map or {}
        self._configured = configured
        # When True, replace_tracks raises SpotifyNotFoundError (simulates deleted playlist).
        self._replace_raises_not_found = replace_raises_not_found
        self.created: dict | None = None
        self.added: list[str] = []
        self.replaced: dict | None = None

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

    async def create_playlist(self, access_token, name, description, *, public=False):
        self.created = {"name": name, "description": description}
        return "pl1", "https://open.spotify.com/playlist/pl1"

    async def add_tracks(self, access_token, playlist_id, uris) -> None:
        self.added.extend(uris)

    async def replace_tracks(self, access_token, playlist_id, uris) -> None:
        if self._replace_raises_not_found:
            raise SpotifyNotFoundError("spotify /playlists/xxx/items returned 404")
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


async def test_callback_redirects_to_home_not_root(spotify_client):
    # An unrecoverable (invalid) state falls back to /home — never / (which
    # hard-redirects to /login and strands the returned user — MYS-92).
    resp = await spotify_client.get("/api/v1/spotify/callback?state=x&error=denied")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/home?spotify=error")


async def test_callback_returns_to_round_from_state(spotify_client, db_session):
    # A valid state carrying return_to lands back on that round (MYS-93). Error
    # path exercises the redirect without mocking the token exchange.
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")
    resp = await spotify_client.get(f"/api/v1/spotify/callback?state={state}&error=denied")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=error")


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
    # The matched uri was added and a playlist with the right name was created.
    assert fake_spotify.added == ["spotify:track:matched"]
    assert fake_spotify.created["name"] == "MysteryMixClub: L, Late Summer"


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


async def test_first_generate_stores_playlist_id_in_db(spotify_client, db_session, fake_spotify):
    # First generate: creates the playlist and writes a SpotifyRoundPlaylist row (MYS-89).
    from sqlalchemy import select

    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    resp = await spotify_client.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text

    organizer_id = organizer.id
    round_id = round_.id
    db_session.expire_all()

    stored = await db_session.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == organizer_id,
        )
    )
    assert stored is not None
    assert stored.playlist_id == "pl1"


async def test_second_generate_reuses_stored_id_without_creating(session_factory, db_session):
    # Second generate: DB row exists → replace_tracks on stored ID, no new playlist (MYS-89).
    fake = FakeSpotifyClient(isrc_map={"I-MATCH": "spotify:track:matched"})
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    # Seed the stored playlist ID directly.
    db_session.add(
        SpotifyRoundPlaylist(round_id=round_.id, user_id=organizer.id, playlist_id="pl-stored")
    )
    await db_session.commit()

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert fake.created is None
    assert fake.replaced == {"playlist_id": "pl-stored", "uris": ["spotify:track:matched"]}
    assert body["playlist_url"] == "https://open.spotify.com/playlist/pl-stored"


async def test_generate_recreates_when_stored_playlist_deleted_in_spotify(
    session_factory, db_session
):
    # replace_tracks 404s (user deleted the playlist in Spotify) → recreate + update stored ID.
    from sqlalchemy import select

    fake = FakeSpotifyClient(
        isrc_map={"I-MATCH": "spotify:track:matched"}, replace_raises_not_found=True
    )
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    db_session.add(
        SpotifyRoundPlaylist(round_id=round_.id, user_id=organizer.id, playlist_id="pl-deleted")
    )
    await db_session.commit()

    organizer_id = organizer.id
    round_id = round_.id

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    # A new playlist was created (the fake always returns "pl1").
    assert fake.created is not None
    assert fake.added == ["spotify:track:matched"]

    db_session.expire_all()
    stored = await db_session.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == organizer_id,
        )
    )
    # Stored ID updated to the new playlist, not the deleted one.
    assert stored is not None
    assert stored.playlist_id == "pl1"


async def test_playlist_track_order_matches_seeded_shuffle(session_factory, db_session):
    # Spotify track order must match random.Random(round_id.int) applied to
    # id-sorted submissions — same algorithm as get_round_playlist (MYS-151).
    # Two known ISRCs both resolve; the shuffle determines which comes first.
    id_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    id_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
    isrc_a, uri_a = "ISRC-A", "spotify:track:aaa"
    isrc_b, uri_b = "ISRC-B", "spotify:track:bbb"
    fake = FakeSpotifyClient(isrc_map={isrc_a: uri_a, isrc_b: uri_b})

    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _connect(db_session, organizer.id)
    other = await _seed_member(db_session, round_, "m2@example.com")

    # Insert in reverse id order so insertion order ≠ id-sorted order.
    db_session.add(
        Submission(
            id=id_b,
            round_id=round_.id,
            user_id=other.id,
            isrc=isrc_b,
            title="B",
            artist="A",
            platform_links={},
        )
    )
    db_session.add(
        Submission(
            id=id_a,
            round_id=round_.id,
            user_id=organizer.id,
            isrc=isrc_a,
            title="A",
            artist="A",
            platform_links={},
        )
    )
    await db_session.commit()

    # Compute expected order: sort by id, then seed-shuffle.
    subs_sorted = sorted([id_a, id_b])
    rng = random.Random(round_.id.int)
    rng.shuffle(subs_sorted)
    expected_uris = [uri_a if sid == id_a else uri_b for sid in subs_sorted]

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.post(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert fake.added == expected_uris
