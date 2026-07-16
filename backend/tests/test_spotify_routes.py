"""Route tests for the Spotify endpoints (MYS-83, MYS-169, MYS-176).

Pre-network gates (auth, open_submission, unconfigured) use the shared
``client`` fixture, where the real Spotify client is unconfigured and those
handlers return before any HTTP call. The connect/status happy paths use a
local app wired with a ``FakeSpotifyClient`` so nothing touches the network.

MYS-169: playlist generation runs off one shared/dedicated Spotify account
(``settings.spotify_playlist_account_user_id``), not the caller's own
connection. ``_SHARED_ACCOUNT_ID`` is a fixed test UUID for that shared
account's app-user id. Generation itself is automatic — triggered on the
``voting_open`` event (MYS-176) — with no manual/admin HTTP trigger; the
generation-engine tests below call
:func:`app.services.spotify_playlist_generation.generate_round_playlist`
directly rather than through a route. Regular members only ever read the
resulting link via ``GET /rounds/:id/spotify-playlist``.
"""

import random
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token, create_oauth_state
from app.config import Settings, get_settings
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
from app.services.spotify_playlist_generation import generate_round_playlist
from app.services.spotify_token_crypto import encrypt_refresh_token
from app.services.youtube_resolver import get_youtube_resolver

# Fixed id for the shared/dedicated playlist account (MYS-169) so tests can wire
# it into Settings before knowing which User row will hold the connection.
_SHARED_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


# --------------------------------------------------------------------------- #
# Seed helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, user_id: uuid.UUID | None = None) -> User:
    user = User(email=email, display_name="U", **({"id": user_id} if user_id else {}))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_shared_account(db_session, *, connected: bool = True) -> User:
    """The dedicated MysteryMixClub Spotify account's app user, at
    ``_SHARED_ACCOUNT_ID`` (MYS-169), optionally with a connection attached."""
    user = await _seed_user(db_session, "playlist-account@example.com", user_id=_SHARED_ACCOUNT_ID)
    if connected:
        await _connect(db_session, user.id)
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

    def __init__(
        self,
        *,
        isrc_map=None,
        configured=True,
        replace_raises_not_found=False,
        exchange_raises: Exception | None = None,
        get_user_id_raises: Exception | None = None,
        exchange_refresh_token: str | None = "rt-new",
    ):
        self._isrc_map = isrc_map or {}
        self._configured = configured
        # When True, replace_tracks raises SpotifyNotFoundError (simulates deleted playlist).
        self._replace_raises_not_found = replace_raises_not_found
        # MYS-169 callback observability: let tests drive exchange_failed / api_error.
        self._exchange_raises = exchange_raises
        self._get_user_id_raises = get_user_id_raises
        self._exchange_refresh_token = exchange_refresh_token
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

    async def exchange_code(self, code) -> SpotifyTokens:
        if self._exchange_raises:
            raise self._exchange_raises
        return SpotifyTokens(
            access_token="tok",
            refresh_token=self._exchange_refresh_token,
            scope="playlist-modify-private",
            expires_in=3600,
        )

    async def refresh_access_token(self, refresh_token) -> SpotifyTokens:
        return SpotifyTokens(
            access_token="user-tok", refresh_token=None, scope=None, expires_in=3600
        )

    async def get_current_user_id(self, access_token) -> str:
        if self._get_user_id_raises:
            raise self._get_user_id_raises
        return "spuser"

    async def create_playlist(self, access_token, name, description, *, public=False):
        self.created = {"name": name, "description": description, "public": public}
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


def _client_with_spotify(
    session_factory,
    fake,
    *,
    playlist_account_id: uuid.UUID | None = _SHARED_ACCOUNT_ID,
) -> AsyncClient:
    """An ASGI client whose Spotify dependency is `fake` (no network, no
    dependence on the ambient .env). Defaults ``SPOTIFY_PLAYLIST_ACCOUNT_USER_ID``
    to ``_SHARED_ACCOUNT_ID`` (MYS-169); pass ``playlist_account_id=None`` to
    exercise the "not configured" path."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_spotify_client] = lambda: fake
    app.dependency_overrides[get_youtube_resolver] = lambda: None
    app.dependency_overrides[get_settings] = lambda: Settings(
        spotify_playlist_account_user_id=str(playlist_account_id) if playlist_account_id else "",
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def spotify_client(session_factory, fake_spotify) -> AsyncGenerator[AsyncClient, None]:
    """Local app wired to a *configured* fake Spotify client and the shared
    playlist account id (its connection is seeded per-test via
    :func:`_seed_shared_account`)."""
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
    # MYS-169: "connected" reflects the shared account, not the caller's own
    # (nonexistent) connection — any authenticated member sees the same status.
    user = await _seed_user(db_session, "u@example.com")
    await _seed_shared_account(db_session)
    resp = await spotify_client.get("/api/v1/spotify/status", headers=_auth(user.id))
    assert resp.json() == {"configured": True, "connected": True}


async def test_status_configured_but_shared_account_not_connected(spotify_client, db_session):
    # App has credentials, but nobody has connected the shared account yet.
    user = await _seed_user(db_session, "u@example.com")
    resp = await spotify_client.get("/api/v1/spotify/status", headers=_auth(user.id))
    assert resp.json() == {"configured": True, "connected": False}


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
    # hard-redirects to /login and strands the returned user — MYS-92). An
    # invalid *state* is indistinguishable from tampering, so it keeps the
    # generic "error" flag rather than one of the MYS-169 specific ones.
    resp = await spotify_client.get("/api/v1/spotify/callback?state=x&error=denied")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/home?spotify=error")


async def test_callback_denied_returns_to_round_from_state(spotify_client, db_session):
    # A valid state carrying return_to lands back on that round (MYS-93). User
    # denying consent (or Spotify erroring before a code is issued) is the
    # "denied" flag (MYS-169 — distinct from exchange_failed/api_error below).
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")
    resp = await spotify_client.get(f"/api/v1/spotify/callback?state={state}&error=denied")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=denied")


async def test_callback_no_code_is_denied(spotify_client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")
    resp = await spotify_client.get(f"/api/v1/spotify/callback?state={state}")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=denied")


async def test_callback_exchange_failure_is_exchange_failed(session_factory, db_session):
    from app.services.spotify_client import SpotifyApiError

    fake = FakeSpotifyClient(exchange_raises=SpotifyApiError("spotify token request returned 500"))
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.get(f"/api/v1/spotify/callback?state={state}&code=abc")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=exchange_failed")


async def test_callback_missing_refresh_token_is_exchange_failed(session_factory, db_session):
    # Exchange "succeeds" but Spotify returned no refresh_token — can't mint
    # future access tokens, so this is treated the same as an exchange failure.
    fake = FakeSpotifyClient(exchange_refresh_token=None)
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.get(f"/api/v1/spotify/callback?state={state}&code=abc")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=exchange_failed")


async def test_callback_get_user_id_failure_is_api_error(session_factory, db_session):
    from app.services.spotify_client import SpotifyApiError

    fake = FakeSpotifyClient(get_user_id_raises=SpotifyApiError("spotify /me returned 500"))
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.get(f"/api/v1/spotify/callback?state={state}&code=abc")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=api_error")


async def test_callback_success_persists_connection_and_redirects_connected(
    session_factory, db_session
):
    from sqlalchemy import select

    fake = FakeSpotifyClient()
    user = await _seed_user(db_session, "u@example.com")
    state = create_oauth_state(user.id, "spotify", "/rounds/r-123")

    async with _client_with_spotify(session_factory, fake) as c:
        resp = await c.get(f"/api/v1/spotify/callback?state={state}&code=abc")
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/rounds/r-123?spotify=connected")

    connection = await db_session.scalar(
        select(SpotifyConnection).where(SpotifyConnection.user_id == user.id)
    )
    assert connection is not None
    assert connection.spotify_user_id == "spuser"


# --------------------------------------------------------------------------- #
# generate_round_playlist — the generation engine (MYS-89, MYS-151, MYS-169)
#
# No HTTP route exercises this directly anymore (admin-triggered generation
# was removed; MYS-176's auto-trigger, tested at the bottom of this file, is
# the only production caller) — so these call the service function directly.
# --------------------------------------------------------------------------- #


async def _generate(db_session, round_: Round, client: FakeSpotifyClient):
    league = await db_session.scalar(select(League).where(League.id == round_.league_id))
    connection = await db_session.scalar(
        select(SpotifyConnection).where(SpotifyConnection.user_id == _SHARED_ACCOUNT_ID)
    )
    return await generate_round_playlist(
        round_.id, round_, league, _SHARED_ACCOUNT_ID, connection, db_session, client
    )


async def test_generate_builds_playlist_and_reports_unmatched(db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    other = await _seed_member(db_session, round_, "m2@example.com")
    # One track resolves via the fake's isrc_map; one does not.
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    await _add_submission(db_session, round_.id, other.id, isrc="I-MISS", title="miss")

    result = await _generate(db_session, round_, fake_spotify)
    assert result.playlist_url == "https://open.spotify.com/playlist/pl1"
    assert result.track_count == 1
    assert result.total_count == 2
    assert len(result.unmatched) == 1
    assert result.unmatched[0].title == "miss"
    # The matched uri was added and a playlist with the right name was created.
    assert fake_spotify.added == ["spotify:track:matched"]
    assert fake_spotify.created["name"] == "MysteryMixClub: L, Late Summer"
    # Playlist is public — no API access needed for members to open the link.
    assert fake_spotify.created["public"] is True


async def test_generate_caches_resolved_uri_on_submission(db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    await _generate(db_session, round_, fake_spotify)

    # The resolved uri should now be cached on the submission row.
    sub = await db_session.scalar(select(Submission).where(Submission.round_id == round_.id))
    assert sub.spotify_track_uri == "spotify:track:matched"


async def test_generate_no_matches_returns_no_playlist(db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MISS", title="miss")

    result = await _generate(db_session, round_, fake_spotify)
    assert result.playlist_url is None
    assert result.track_count == 0
    assert fake_spotify.created is None  # no empty playlist created


async def test_first_generate_stores_playlist_id_in_db(db_session, fake_spotify):
    # First generate: creates the playlist and writes a SpotifyRoundPlaylist row (MYS-89).
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    await _generate(db_session, round_, fake_spotify)

    round_id = round_.id
    db_session.expire_all()

    # Stored against the shared account (MYS-169).
    stored = await db_session.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == _SHARED_ACCOUNT_ID,
        )
    )
    assert stored is not None
    assert stored.playlist_id == "pl1"


async def test_second_generate_reuses_stored_id_without_creating(db_session):
    # Second generate: DB row exists → replace_tracks on stored ID, no new playlist (MYS-89).
    fake = FakeSpotifyClient(isrc_map={"I-MATCH": "spotify:track:matched"})
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    # Seed the stored playlist ID directly, keyed to the shared account (MYS-169).
    db_session.add(
        SpotifyRoundPlaylist(
            round_id=round_.id, user_id=_SHARED_ACCOUNT_ID, playlist_id="pl-stored"
        )
    )
    await db_session.commit()

    result = await _generate(db_session, round_, fake)
    assert fake.created is None
    assert fake.replaced == {"playlist_id": "pl-stored", "uris": ["spotify:track:matched"]}
    assert result.playlist_url == "https://open.spotify.com/playlist/pl-stored"


async def test_generate_recreates_when_stored_playlist_deleted_in_spotify(db_session):
    # replace_tracks 404s (user deleted the playlist in Spotify) → recreate + update stored ID.
    fake = FakeSpotifyClient(
        isrc_map={"I-MATCH": "spotify:track:matched"}, replace_raises_not_found=True
    )
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")
    db_session.add(
        SpotifyRoundPlaylist(
            round_id=round_.id, user_id=_SHARED_ACCOUNT_ID, playlist_id="pl-deleted"
        )
    )
    await db_session.commit()

    round_id = round_.id

    await _generate(db_session, round_, fake)
    # A new playlist was created (the fake always returns "pl1").
    assert fake.created is not None
    assert fake.added == ["spotify:track:matched"]

    db_session.expire_all()
    stored = await db_session.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == _SHARED_ACCOUNT_ID,
        )
    )
    # Stored ID updated to the new playlist, not the deleted one.
    assert stored is not None
    assert stored.playlist_id == "pl1"


async def test_playlist_track_order_matches_seeded_shuffle(db_session):
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
    await _seed_shared_account(db_session)
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

    await _generate(db_session, round_, fake)
    assert fake.added == expected_uris


# --------------------------------------------------------------------------- #
# read-only link — GET /rounds/:id/spotify-playlist (MYS-169)
# --------------------------------------------------------------------------- #


def _link_url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/spotify-playlist"


async def test_link_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.get(_link_url(round_.id))
    assert resp.status_code == 401


async def test_link_requires_league_membership(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.get(_link_url(round_.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_link_null_before_generation(spotify_client, db_session):
    # Shared account is even connected here — still null because nothing has
    # been generated yet (read-only: this endpoint never generates).
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    resp = await spotify_client.get(_link_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200
    assert resp.json() == {"playlist_url": None}


async def test_link_null_when_shared_account_not_configured(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.get(_link_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200
    assert resp.json() == {"playlist_url": None}


async def test_link_visible_to_any_member_after_generation(
    spotify_client, db_session, fake_spotify
):
    # A member who never touched Spotify still sees the link once it's been
    # generated (MYS-169) — this endpoint is read-only for everyone.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_shared_account(db_session)
    member = await _seed_member(db_session, round_, "m@example.com")
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    await _generate(db_session, round_, fake_spotify)

    link_resp = await spotify_client.get(_link_url(round_.id), headers=_auth(member.id))
    assert link_resp.status_code == 200
    assert link_resp.json() == {"playlist_url": "https://open.spotify.com/playlist/pl1"}


# --------------------------------------------------------------------------- #
# auto-generation on voting_open (MYS-176) — no admin click needed
# --------------------------------------------------------------------------- #


async def test_voting_open_auto_generates_playlist(spotify_client, db_session, fake_spotify):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer, state="open_submission")
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    resp = await spotify_client.patch(
        f"/api/v1/rounds/{round_.id}", json={"state": "open_voting"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 200, resp.text

    link = await spotify_client.get(_playlist_url(round_.id), headers=_auth(organizer.id))
    assert link.json()["playlist_url"] == "https://open.spotify.com/playlist/pl1"
    assert fake_spotify.created["public"] is True


async def test_voting_open_does_not_auto_generate_when_unconfigured(client, db_session):
    # `client` (conftest's default fixture) has no SPOTIFY_PLAYLIST_ACCOUNT_USER_ID
    # set — the round transition must succeed exactly as before MYS-176.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer, state="open_submission")
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    resp = await client.patch(
        f"/api/v1/rounds/{round_.id}", json={"state": "open_voting"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open_voting"


async def test_voting_open_auto_generate_failure_does_not_block_transition(
    session_factory, db_session
):
    # A revoked shared-account grant must not prevent voting from opening —
    # auto-generation is best-effort (MYS-176).
    from app.services.spotify_client import SpotifyAuthError

    class _RejectingClient(FakeSpotifyClient):
        async def refresh_access_token(self, refresh_token):
            raise SpotifyAuthError("invalid_grant")

    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer, state="open_submission")
    await _seed_shared_account(db_session)
    await _add_submission(db_session, round_.id, organizer.id, isrc="I-MATCH", title="hit")

    async with _client_with_spotify(session_factory, _RejectingClient()) as ac:
        resp = await ac.patch(
            f"/api/v1/rounds/{round_.id}",
            json={"state": "open_voting"},
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open_voting"
