"""Tests for MYS-49: input-sanitization hardening (bounded text fields).

The developer bounded several text fields via Pydantic ``StringConstraints``.
This suite is a boundary/abuse-input harness: it locks the newly bounded /
changed fields (league description, submission note/album/album_art_url) at
their length edges and trim behaviour, regression-locks the existing bounded
fields (display_name, league name, round theme, submission title, notes body),
and documents the chosen XSS posture (bound + escape-on-render, NOT
server-side HTML stripping) by asserting malicious markup round-trips verbatim.

Constraints under test (violations -> 422 via Pydantic):

| Field                    | endpoint                          | strip | min | max  |
|--------------------------|-----------------------------------|-------|-----|------|
| display_name             | PATCH /users/me                   | yes   | 1   | 50   |
| league name              | POST/PATCH /leagues               | yes   | 1   | 100  |
| league description       | POST/PATCH /leagues               | yes   | -   | 2000 |
| round theme              | POST /leagues/:id/rounds          | yes   | 1   | 200  |
| submission title/artist  | POST /rounds/:id/submissions      | yes   | 1   | 500  |
| submission note          | POST /rounds/:id/submissions      | yes   | -   | 280  |
| album                    | POST /rounds/:id/submissions      | yes   | -   | 500  |
| album_art_url            | POST /rounds/:id/submissions      | NO    | -   | 2048 |
| notes body               | POST /submissions/:id/notes       | yes   | 1   | 280  |

Submissions need a ``open_submission`` round; notes need ``open_voting``.

The submissions endpoints depend on the keyless link assembler, so those tests
build their own client with the assembler overridden (mirroring
test_submissions.py). Everything else uses the shared ``client`` fixture.
"""

import uuid
from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.song_links import get_link_assembler
from app.services.youtube_resolver import get_youtube_resolver

ME_URL = "/api/v1/users/me"
LEAGUES_URL = "/api/v1/leagues"

_LINKS = {
    "spotify": "https://open.spotify.com/search/x",
    "youtube": "https://music.youtube.com/search?q=x",
}


# --------------------------------------------------------------------------- #
# Submissions client (assembler overridden, no live HTTP)
# --------------------------------------------------------------------------- #


class _FakeAssembler:
    async def assemble(self, title, artist=None, isrc=None) -> dict[str, str]:
        return _LINKS


class _FakeYouTube:
    async def video_id_for(self, title, artist=None) -> str | None:
        return None


def _build_client(session_factory) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_link_assembler] = lambda: _FakeAssembler()
    # Keep submit-path tests offline — no live YouTube API.
    app.dependency_overrides[get_youtube_resolver] = lambda: _FakeYouTube()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str = "alice@example.com", name: str = "Alice") -> User:
    user = User(email=email, display_name=name, default_vibe_mode=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer: User, **overrides) -> League:
    defaults = {
        "name": "Summer Bangers",
        "organizer_id": organizer.id,
        "total_rounds": 6,
        "votes_per_player": 3,
    }
    defaults.update(overrides)
    league = League(**defaults)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_league_with_round(
    db_session, organizer: User, *, state: str = "open_submission"
) -> Round:
    league = League(name="L", organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(league_id=league.id, round_number=1, theme="late summer", state=state)
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _seed_submission(db_session, round_: Round, user: User) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title="bad guy",
        artist="Billie Eilish",
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _league_body(**over) -> dict:
    body = {"name": "Summer Bangers", "total_rounds": 6, "votes_per_player": 3}
    body.update(over)
    return body


def _sub_body(**over) -> dict:
    body = {"isrc": "USABC1234567", "title": "bad guy", "artist": "Billie Eilish"}
    body.update(over)
    return body


def _sub_url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/submissions"


def _notes_url(submission_id) -> str:
    return f"/api/v1/submissions/{submission_id}/notes"


# ========================================================================== #
# 1. league description — POST /leagues (newly bounded: strip + max 2000)
# ========================================================================== #


async def test_create_description_exactly_2000_accepted(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL, headers=_auth(user.id), json=_league_body(description="d" * 2000)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "d" * 2000


async def test_create_description_2001_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL, headers=_auth(user.id), json=_league_body(description="d" * 2001)
    )
    assert resp.status_code == 422, resp.text


async def test_create_description_strips_before_length_check(client, db_session):
    # strip happens before length validation, so leading whitespace + 2000 body
    # chars trims back to 2000 and is accepted.
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL,
        headers=_auth(user.id),
        json=_league_body(description=" " * 5 + "d" * 2000 + " " * 5),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == "d" * 2000


async def test_create_description_whitespace_only_trims_to_empty_accepted(client, db_session):
    # description is optional (no min_length): whitespace-only trims to "" and is
    # accepted (stored as the empty string, not rejected).
    user = await _seed_user(db_session)
    resp = await client.post(
        LEAGUES_URL, headers=_auth(user.id), json=_league_body(description="     ")
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["description"] == ""


# ========================================================================== #
# 1b. league description — PATCH /leagues
# ========================================================================== #


async def test_patch_description_exactly_2000_accepted(client, db_session):
    user = await _seed_user(db_session)
    league = await _seed_league(db_session, user)
    resp = await client.patch(
        f"{LEAGUES_URL}/{league.id}", headers=_auth(user.id), json={"description": "d" * 2000}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "d" * 2000


async def test_patch_description_2001_returns_422(client, db_session):
    user = await _seed_user(db_session)
    league = await _seed_league(db_session, user)
    resp = await client.patch(
        f"{LEAGUES_URL}/{league.id}", headers=_auth(user.id), json={"description": "d" * 2001}
    )
    assert resp.status_code == 422, resp.text


async def test_patch_description_strips_before_length_check(client, db_session):
    user = await _seed_user(db_session)
    league = await _seed_league(db_session, user)
    resp = await client.patch(
        f"{LEAGUES_URL}/{league.id}",
        headers=_auth(user.id),
        json={"description": " " * 5 + "d" * 2000},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "d" * 2000


async def test_patch_explicit_null_description_still_accepted_and_clears(client, db_session):
    # The _reject_explicit_null validator must NOT cover description (nullable):
    # explicit null clears it and returns 200.
    user = await _seed_user(db_session)
    league = await _seed_league(db_session, user, description="has a description")
    league_id = league.id
    resp = await client.patch(
        f"{LEAGUES_URL}/{league_id}", headers=_auth(user.id), json={"description": None}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] is None

    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.id == league_id))
    assert persisted.description is None


# ========================================================================== #
# 2. submission note — now strips; max 280
# ========================================================================== #


async def test_submission_note_is_trimmed(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_id),
            json=_sub_body(note="  a quiet banger  "),
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["note"] == "a quiet banger"

    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.note == "a quiet banger"


async def test_submission_note_exactly_280_accepted(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(note="n" * 280), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["note"] == "n" * 280


async def test_submission_note_281_returns_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(note="n" * 281), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


# ========================================================================== #
# 3. album (strip, max 500) + album_art_url (NO strip, max 2048)
# ========================================================================== #


async def test_submission_album_exactly_500_accepted(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(album="a" * 500), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["album"] == "a" * 500


async def test_submission_album_501_returns_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(album="a" * 501), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


async def test_submission_album_is_trimmed(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_id),
            json=_sub_body(album="  When We All Fall Asleep  "),
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["album"] == "When We All Fall Asleep"


async def test_submission_album_art_url_exactly_2048_accepted(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    # 2048 chars with no surrounding whitespace (url is NOT stripped).
    url = "https://img.example.com/" + "a" * (2048 - len("https://img.example.com/"))
    assert len(url) == 2048
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(album_art_url=url), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["album_art_url"] == url


async def test_submission_album_art_url_2049_returns_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    url = "https://img.example.com/" + "a" * (2049 - len("https://img.example.com/"))
    assert len(url) == 2049
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(album_art_url=url), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


async def test_submission_album_art_url_not_stripped(session_factory, db_session):
    # album_art_url has no strip_whitespace: surrounding spaces are preserved
    # verbatim (they count toward length, and are not trimmed from the stored
    # value). 2046 url chars + 2 spaces = 2048, accepted, stored with spaces.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    core = "https://img.example.com/" + "a" * (2046 - len("https://img.example.com/"))
    url = " " + core + " "
    assert len(url) == 2048
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_id), json=_sub_body(album_art_url=url), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    # Not trimmed: the surrounding spaces survive round-trip.
    assert resp.json()["album_art_url"] == url

    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.album_art_url == url


# ========================================================================== #
# 4. Existing bounded fields — regression lock
# ========================================================================== #


async def test_display_name_51_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.patch(ME_URL, headers=_auth(user.id), json={"display_name": "x" * 51})
    assert resp.status_code == 422, resp.text


async def test_display_name_50_accepted(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.patch(ME_URL, headers=_auth(user.id), json={"display_name": "x" * 50})
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "x" * 50


async def test_league_name_101_returns_422(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(LEAGUES_URL, headers=_auth(user.id), json=_league_body(name="x" * 101))
    assert resp.status_code == 422, resp.text


async def test_league_name_100_accepted(client, db_session):
    user = await _seed_user(db_session)
    resp = await client.post(LEAGUES_URL, headers=_auth(user.id), json=_league_body(name="x" * 100))
    assert resp.status_code == 201, resp.text


async def test_round_theme_201_returns_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.post(
        f"{LEAGUES_URL}/{league.id}/rounds",
        headers=_auth(organizer.id),
        json={"theme": "t" * 201},
    )
    assert resp.status_code == 422, resp.text


async def test_round_theme_200_accepted(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.post(
        f"{LEAGUES_URL}/{league.id}/rounds",
        headers=_auth(organizer.id),
        json={"theme": "t" * 200},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["theme"] == "t" * 200


async def test_submission_title_501_returns_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(title="t" * 501), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


async def test_submission_title_500_accepted(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_sub_body(title="t" * 500), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "t" * 500


async def test_notes_body_281_returns_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(
        _notes_url(sub.id), json={"body": "b" * 281}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 422, resp.text


async def test_notes_body_empty_returns_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_notes_url(sub.id), json={"body": ""}, headers=_auth(organizer.id))
    assert resp.status_code == 422, resp.text


async def test_notes_body_whitespace_only_returns_422(client, db_session):
    # strip_whitespace + min_length=1: whitespace-only collapses to "" and fails.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_notes_url(sub.id), json={"body": "    "}, headers=_auth(organizer.id))
    assert resp.status_code == 422, resp.text


# ========================================================================== #
# 5. XSS posture — payload stored verbatim (bound + escape-on-render)
# ========================================================================== #
# The chosen approach is to BOUND length and ESCAPE at render time on the
# frontend, NOT to strip/mutate HTML server-side. These tests prove the server
# stores user text byte-for-byte and does not silently alter it.


_XSS = "<script>alert(1)</script>"


async def test_league_name_xss_payload_round_trips_verbatim(client, db_session):
    user = await _seed_user(db_session)
    user_id = user.id  # capture PK before expire_all()
    resp = await client.post(LEAGUES_URL, headers=_auth(user_id), json=_league_body(name=_XSS))
    assert resp.status_code == 201, resp.text
    # Stored and echoed exactly — no HTML stripping or entity encoding server-side.
    assert resp.json()["name"] == _XSS

    db_session.expire_all()
    persisted = await db_session.scalar(select(League).where(League.organizer_id == user_id))
    assert persisted.name == _XSS


async def test_note_body_xss_payload_round_trips_verbatim(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id = sub.id
    resp = await client.post(_notes_url(sub_id), json={"body": _XSS}, headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["body"] == _XSS

    db_session.expire_all()
    stored = await db_session.scalar(select(Note).where(Note.submission_id == sub_id))
    assert stored.body == _XSS


# ========================================================================== #
# 6. /songs endpoints — newly bounded search params + resolve body (MYS-49)
# ========================================================================== #
# GET /songs/search:  q (min 1, max 200, no strip), artist (optional, max 200,
#   no strip).
# POST /songs/resolve body (ResolveRequest):
#   url (max 2048, NO strip), title/artist/album (max 500, strip),
#   isrc (max 32, strip), thumbnail_url (max 2048, NO strip).
#   The model also requires url-or-title (existing validator).
#
# Both endpoints need auth (get_current_user) and dependency-injected service
# clients. We mock Deezer (search) / link resolver + assembler (resolve) so a 422
# (validation) is reached BEFORE any external call, and valid requests still
# resolve via the mock (positive controls). For the 422 boundary cases the
# external mock may never be invoked — that is expected and correct.

from app.services.deezer_search import (  # noqa: E402
    SongSearchResult,
    SongTrack,
    get_deezer_client,
)
from app.services.link_resolver import SongIdentity, get_link_resolver  # noqa: E402

SEARCH_URL = "/api/v1/songs/search"
RESOLVE_URL = "/api/v1/songs/resolve"

_ASSEMBLED = {
    "spotify": "https://open.spotify.com/search/x",
    "youtube": "https://music.youtube.com/search?q=x",
}

_RESOLVED_SONG = SongIdentity(
    title="bad guy",
    artist="Billie Eilish",
    album=None,
    thumbnail_url="https://img/x.jpg",
    isrc="USUM71900764",
)


class _FakeDeezerSearch:
    """Returns a single canned result for any search; never hits the network."""

    async def search(self, title: str, artist: str | None = None) -> SongSearchResult:
        return SongSearchResult(
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


class _FakeLinkResolve:
    async def resolve(self, url: str) -> SongIdentity:
        return _RESOLVED_SONG


class _FakeResolveAssembler:
    async def assemble(self, title, artist=None, isrc=None) -> dict[str, str]:
        return _ASSEMBLED


def _build_songs_client(session_factory) -> AsyncClient:
    """Client with get_db + Deezer/resolver/assembler overridden (no live HTTP)."""
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_deezer_client] = lambda: _FakeDeezerSearch()
    app.dependency_overrides[get_link_resolver] = lambda: _FakeLinkResolve()
    app.dependency_overrides[get_link_assembler] = lambda: _FakeResolveAssembler()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _resolve_body(**over) -> dict:
    body = {"title": "bad guy", "artist": "Billie Eilish"}
    body.update(over)
    return body


# --------------------------------------------------------------------------- #
# 6a. GET /songs/search — q (min 1, max 200), artist (optional, max 200)
# --------------------------------------------------------------------------- #


async def test_search_q_exactly_200_accepted(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(SEARCH_URL, params={"q": "a" * 200}, headers=_auth(user.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["id"] == "id0"


async def test_search_q_201_returns_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(SEARCH_URL, params={"q": "a" * 201}, headers=_auth(user.id))
    assert resp.status_code == 422, resp.text


async def test_search_q_missing_returns_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(SEARCH_URL, headers=_auth(user.id))
    assert resp.status_code == 422, resp.text


async def test_search_q_empty_returns_422(session_factory, db_session):
    # min_length=1: empty string fails before the Deezer client is called.
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(SEARCH_URL, params={"q": ""}, headers=_auth(user.id))
    assert resp.status_code == 422, resp.text


async def test_search_artist_exactly_200_accepted(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(
            SEARCH_URL,
            params={"q": "song", "artist": "a" * 200},
            headers=_auth(user.id),
        )
    assert resp.status_code == 200, resp.text


async def test_search_artist_201_returns_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.get(
            SEARCH_URL,
            params={"q": "song", "artist": "a" * 201},
            headers=_auth(user.id),
        )
    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# 6b. POST /songs/resolve — positive control + field bounds
# --------------------------------------------------------------------------- #


async def test_resolve_in_bounds_payload_accepted(session_factory, db_session):
    # Positive control: a valid in-bounds identity payload resolves via the mock.
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL,
            json=_resolve_body(isrc="USUM71900764", album="When We All Fall Asleep"),
            headers=_auth(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "bad guy"
    assert set(body["platforms"]) == {"spotify", "youtube"}


async def test_resolve_title_exactly_500_accepted(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(title="t" * 500), headers=_auth(user.id)
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "t" * 500


async def test_resolve_title_501_returns_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(title="t" * 501), headers=_auth(user.id)
        )
    assert resp.status_code == 422, resp.text


async def test_resolve_isrc_33_returns_422(session_factory, db_session):
    # isrc max 32; a valid title is present so the 422 is attributable to isrc.
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(isrc="i" * 33), headers=_auth(user.id)
        )
    assert resp.status_code == 422, resp.text


async def test_resolve_album_501_returns_422(session_factory, db_session):
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(album="a" * 501), headers=_auth(user.id)
        )
    assert resp.status_code == 422, resp.text


async def test_resolve_url_2049_returns_422(session_factory, db_session):
    # url max 2048. Sent as the sole identity (url-or-title satisfied by url).
    user = await _seed_user(db_session)
    url = "https://open.spotify.com/track/" + "a" * (2049 - len("https://open.spotify.com/track/"))
    assert len(url) == 2049
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(RESOLVE_URL, json={"url": url}, headers=_auth(user.id))
    assert resp.status_code == 422, resp.text


async def test_resolve_thumbnail_url_2049_returns_422(session_factory, db_session):
    # thumbnail_url max 2048; a valid title is present so the 422 is attributable
    # to thumbnail_url.
    user = await _seed_user(db_session)
    thumb = "https://img.example.com/" + "a" * (2049 - len("https://img.example.com/"))
    assert len(thumb) == 2049
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(thumbnail_url=thumb), headers=_auth(user.id)
        )
    assert resp.status_code == 422, resp.text


async def test_resolve_title_isrc_album_strip_whitespace(session_factory, db_session):
    # title / isrc / album strip surrounding whitespace before length checks and
    # in the echoed/resolved output.
    user = await _seed_user(db_session)
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL,
            json=_resolve_body(
                title="  bad guy  ",
                isrc="  USUM71900764  ",
                album="  When We All Fall Asleep  ",
            ),
            headers=_auth(user.id),
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "bad guy"
    assert body["isrc"] == "USUM71900764"
    assert body["album"] == "When We All Fall Asleep"


async def test_resolve_thumbnail_url_not_stripped(session_factory, db_session):
    # thumbnail_url has no strip_whitespace: surrounding spaces survive verbatim
    # and count toward length. 2046 url chars + 2 spaces = 2048, accepted.
    user = await _seed_user(db_session)
    core = "https://img.example.com/" + "a" * (2046 - len("https://img.example.com/"))
    thumb = " " + core + " "
    assert len(thumb) == 2048
    async with _build_songs_client(session_factory) as client:
        resp = await client.post(
            RESOLVE_URL, json=_resolve_body(thumbnail_url=thumb), headers=_auth(user.id)
        )
    assert resp.status_code == 200, resp.text
    # Not trimmed: the surrounding spaces survive round-trip.
    assert resp.json()["thumbnail_url"] == thumb
