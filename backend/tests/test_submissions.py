"""Tests for MYS-51: song submission endpoints.

The Odesli dependency is overridden with a fake (no live HTTP). Covers
auth/membership gates, the round-state gate, the happy path + odesli_data
persistence, best-effort behaviour when Odesli fails, replace-in-place (one
submission per user per round), participation-mode defaulting, and the
read endpoints (mine, and the reveal-after-close list gate).
"""

import uuid
from collections.abc import AsyncGenerator

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.odesli import OdesliRateLimitError, ResolvedSong, get_odesli_client

_RAW = {"entityUniqueId": "SPOTIFY_SONG::1", "linksByPlatform": {"spotify": {"url": "https://s"}}}


class _FakeOdesli:
    def __init__(self, *, raw=_RAW, error: Exception | None = None):
        self._raw = raw
        self._error = error

    async def resolve_with_raw(self, url: str):
        if self._error:
            raise self._error
        return ResolvedSong(title="t", platforms={}), self._raw


def _build_client(session_factory, *, odesli) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_odesli_client] = lambda: odesli
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, vibe: bool = False) -> User:
    user = User(email=email, display_name="U", default_vibe_mode=vibe)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


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


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _body(**over) -> dict:
    body = {
        "url": "https://www.deezer.com/track/1",
        "isrc": "USABC1234567",
        "title": "bad guy",
        "artist": "Billie Eilish",
    }
    body.update(over)
    return body


def _sub_url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/submissions"


# --------------------------------------------------------------------------- #
# POST — gates
# --------------------------------------------------------------------------- #


async def test_submit_requires_auth(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(round_.id), json=_body())
    assert resp.status_code == 401


async def test_submit_non_member_forbidden(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_submit_to_unknown_round_404(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(uuid.uuid4()), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 404


async def test_submit_when_not_open_for_submission_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_submit_note_too_long_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_body(note="x" * 281), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422


async def test_submit_missing_isrc_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    body = _body()
    del body["isrc"]
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(round_.id), json=body, headers=_auth(organizer.id))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# POST — happy paths
# --------------------------------------------------------------------------- #


async def test_submit_happy_path_persists_odesli_data(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(
            _sub_url(round_id), json=_body(note="a quiet banger"), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["isrc"] == "USABC1234567"
    assert body["title"] == "bad guy"
    assert body["participation_mode"] == "playing"
    assert body["note"] == "a quiet banger"
    # odesli_data is stored server-side (not exposed in the response).
    assert "odesli_data" not in body
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.odesli_data == _RAW


async def test_submit_defaults_to_vibing_for_vibe_user(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com", vibe=True)
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201
    assert resp.json()["participation_mode"] == "vibing"


async def test_submit_explicit_mode_overrides_default(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com", vibe=True)
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.post(
            _sub_url(round_.id),
            json=_body(participation_mode="playing"),
            headers=_auth(organizer.id),
        )
    assert resp.json()["participation_mode"] == "playing"


async def test_submit_best_effort_when_odesli_fails(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    fake = _FakeOdesli(error=OdesliRateLimitError())
    async with _build_client(session_factory, odesli=fake) as client:
        resp = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
    # Submission still succeeds; odesli_data is just null.
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.odesli_data is None


async def test_resubmit_replaces_in_place(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        first = await client.post(
            _sub_url(round_id), json=_body(title="first pick"), headers=_auth(organizer.id)
        )
        assert first.status_code == 201
        second = await client.post(
            _sub_url(round_id),
            json=_body(title="changed my mind", isrc="GBXYZ9999999"),
            headers=_auth(organizer.id),
        )
    assert second.status_code == 200, second.text
    assert second.json()["title"] == "changed my mind"
    assert second.json()["isrc"] == "GBXYZ9999999"
    # Exactly one row for this (round, user).
    db_session.expire_all()
    count = await db_session.scalar(
        select(func.count()).select_from(Submission).where(Submission.round_id == round_id)
    )
    assert count == 1


# --------------------------------------------------------------------------- #
# GET mine
# --------------------------------------------------------------------------- #


async def test_get_mine_returns_submission(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        resp = await client.get(f"{_sub_url(round_.id)}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "bad guy"


async def test_get_mine_404_when_none(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.get(f"{_sub_url(round_.id)}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# GET list (reveal after close)
# --------------------------------------------------------------------------- #


async def test_list_hidden_before_close_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        resp = await client.get(_sub_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_list_visible_after_close(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    # Seed an open round, submit, then flip to closed directly in the DB.
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    round_id = round_.id
    async with _build_client(session_factory, odesli=_FakeOdesli()) as client:
        await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
        await client.post(
            _sub_url(round_id), json=_body(title="member pick"), headers=_auth(member.id)
        )
        # Close the round (membership read still allowed).
        db_round = await db_session.scalar(select(Round).where(Round.id == round_id))
        db_round.state = "closed"
        await db_session.commit()
        resp = await client.get(_sub_url(round_id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    titles = sorted(s["title"] for s in resp.json())
    assert titles == ["bad guy", "member pick"]
