"""Tests for MYS-51 + MYS-116: song submission endpoints.

The link assembler is overridden with a fake (no live HTTP). Covers
auth/membership gates, the round-state gate, the happy path + platform_links
persistence, degraded-links behaviour, the per-league songs_per_submission cap
(add up to the cap, then 409), edit (PATCH) + delete of individual songs,
uniform per-player vibe stance across a player's songs, participation-mode
defaulting, and the read endpoints (mine as a list, and the reveal-after-close
list gate).
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
from app.services.song_links import get_link_assembler
from app.services.youtube_resolver import get_youtube_resolver

_LINKS = {
    "spotify": "https://open.spotify.com/search/bad%20guy",
    "appleMusic": "https://music.apple.com/track/9",
    "deezer": "https://www.deezer.com/track/1",
    "youtube": "https://music.youtube.com/search?q=bad%20guy",
}


class _FakeAssembler:
    def __init__(self, links: dict[str, str] | None = None):
        self._links = _LINKS if links is None else links

    async def assemble(self, title, artist=None, isrc=None) -> dict[str, str]:
        return self._links


class _FakeYouTube:
    """Returns a fixed video id (or None) so submit tests never hit the real API."""

    def __init__(self, video_id: str | None = None):
        self._video_id = video_id

    async def video_id_for(self, title, artist=None) -> str | None:
        return self._video_id


def _build_client(session_factory, *, assembler=None, youtube=None) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_link_assembler] = lambda: assembler or _FakeAssembler()
    # Always override the YouTube resolver so submit tests stay offline.
    app.dependency_overrides[get_youtube_resolver] = lambda: youtube or _FakeYouTube()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league_with_round(
    db_session,
    organizer: User,
    *,
    state: str = "open_submission",
    vibe: bool = False,
    songs: int = 1,
) -> Round:
    # `vibe` seeds the organizer's per-league vibe_mode, so their submission
    # defaults to that mode (MYS-112). `songs` is the per-league songs_per_submission
    # cap (MYS-116; default 1 = classic one-song behaviour).
    league = League(
        name="L",
        organizer_id=organizer.id,
        total_rounds=3,
        votes_per_player=3,
        songs_per_submission=songs,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id, vibe_mode=vibe))
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
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=_body())
    assert resp.status_code == 401


async def test_submit_non_member_forbidden(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_submit_to_unknown_round_404(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(uuid.uuid4()), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 404


async def test_submit_when_not_open_for_submission_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_submit_note_too_long_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_body(note="x" * 281), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422


async def test_submit_missing_isrc_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    body = _body()
    del body["isrc"]
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=body, headers=_auth(organizer.id))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# POST — happy paths
# --------------------------------------------------------------------------- #


async def test_submit_happy_path_persists_platform_links(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_id), json=_body(note="a quiet banger"), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["isrc"] == "USABC1234567"
    assert body["title"] == "bad guy"
    assert body["participation_mode"] == "playing"
    assert body["note"] == "a quiet banger"
    # platform_links are stored server-side (not exposed in the response).
    assert "platform_links" not in body
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.platform_links == _LINKS


async def test_submit_resolves_and_persists_youtube_video_id(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    youtube = _FakeYouTube(video_id="PRpiBpDy7MQ")
    async with _build_client(session_factory, youtube=youtube) as client:
        resp = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.youtube_video_id == "PRpiBpDy7MQ"


async def test_submit_succeeds_when_youtube_resolution_yields_none(session_factory, db_session):
    # A failed/empty YouTube resolve must not block the submission.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    youtube = _FakeYouTube(video_id=None)
    async with _build_client(session_factory, youtube=youtube) as client:
        resp = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.youtube_video_id is None


async def test_edit_updates_youtube_video_id(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory, youtube=_FakeYouTube(video_id="FIRST")) as client:
        first = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
        assert first.status_code == 201
        sid = first.json()["id"]
    async with _build_client(session_factory, youtube=_FakeYouTube(video_id="SECOND")) as client:
        edited = await client.patch(
            f"{_sub_url(round_id)}/{sid}", json=_body(title="new pick"), headers=_auth(organizer.id)
        )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "new pick"
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.youtube_video_id == "SECOND"


async def test_submit_defaults_to_vibing_for_vibe_user(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, vibe=True)
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201
    assert resp.json()["participation_mode"] == "vibing"


async def test_submit_explicit_mode_overrides_default(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, vibe=True)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id),
            json=_body(participation_mode="playing"),
            headers=_auth(organizer.id),
        )
    assert resp.json()["participation_mode"] == "playing"


async def test_submit_succeeds_with_degraded_links(session_factory, db_session):
    # If the assembler can only return some links (or none), the submission
    # still succeeds — whatever it returns is stored as-is.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    degraded = _FakeAssembler({"deezer": "https://www.deezer.com/search/x"})
    async with _build_client(session_factory, assembler=degraded) as client:
        resp = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.round_id == round_id))
    assert stored.platform_links == {"deezer": "https://www.deezer.com/search/x"}


# --------------------------------------------------------------------------- #
# POST — songs_per_submission cap (MYS-116)
# --------------------------------------------------------------------------- #


async def test_submit_at_cap_409(session_factory, db_session):
    # Default cap is 1: a second song from the same player is rejected.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        first = await client.post(
            _sub_url(round_.id), json=_body(title="first"), headers=_auth(organizer.id)
        )
        assert first.status_code == 201
        second = await client.post(
            _sub_url(round_.id), json=_body(title="second"), headers=_auth(organizer.id)
        )
    assert second.status_code == 409, second.text
    assert "maximum" in second.json()["detail"]


async def test_submit_multiple_up_to_cap(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, songs=3)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        for i in range(3):
            resp = await client.post(
                _sub_url(round_id), json=_body(title=f"pick {i}"), headers=_auth(organizer.id)
            )
            assert resp.status_code == 201, resp.text
        # The 4th exceeds the cap of 3.
        over = await client.post(
            _sub_url(round_id), json=_body(title="too many"), headers=_auth(organizer.id)
        )
    assert over.status_code == 409, over.text
    db_session.expire_all()
    count = await db_session.scalar(
        select(func.count()).select_from(Submission).where(Submission.round_id == round_id)
    )
    assert count == 3


# --------------------------------------------------------------------------- #
# PATCH / DELETE — manage individual songs (MYS-116)
# --------------------------------------------------------------------------- #


async def test_edit_replaces_track(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        first = await client.post(
            _sub_url(round_.id), json=_body(title="first pick"), headers=_auth(organizer.id)
        )
        sid = first.json()["id"]
        edited = await client.patch(
            f"{_sub_url(round_.id)}/{sid}",
            json=_body(title="changed my mind", isrc="GBXYZ9999999"),
            headers=_auth(organizer.id),
        )
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "changed my mind"
    assert edited.json()["isrc"] == "GBXYZ9999999"
    assert edited.json()["id"] == sid


async def test_edit_not_your_submission_403(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    async with _build_client(session_factory) as client:
        mine = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        sid = mine.json()["id"]
        resp = await client.patch(
            f"{_sub_url(round_.id)}/{sid}", json=_body(title="hijack"), headers=_auth(member.id)
        )
    assert resp.status_code == 403


async def test_edit_unknown_submission_404(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.patch(
            f"{_sub_url(round_.id)}/{uuid.uuid4()}", json=_body(), headers=_auth(organizer.id)
        )
    assert resp.status_code == 404


async def test_edit_when_not_open_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        first = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
        sid = first.json()["id"]
        db_round = await db_session.scalar(select(Round).where(Round.id == round_id))
        db_round.state = "open_voting"
        await db_session.commit()
        resp = await client.patch(
            f"{_sub_url(round_id)}/{sid}", json=_body(title="late"), headers=_auth(organizer.id)
        )
    assert resp.status_code == 409


async def test_delete_removes_song(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, songs=2)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        a = await client.post(
            _sub_url(round_id), json=_body(title="keep"), headers=_auth(organizer.id)
        )
        b = await client.post(
            _sub_url(round_id), json=_body(title="drop"), headers=_auth(organizer.id)
        )
        resp = await client.delete(
            f"{_sub_url(round_id)}/{b.json()['id']}", headers=_auth(organizer.id)
        )
        assert resp.status_code == 204, resp.text
        mine = await client.get(f"{_sub_url(round_id)}/mine", headers=_auth(organizer.id))
    titles = [s["title"] for s in mine.json()]
    assert titles == ["keep"]
    assert a.json()["id"] != b.json()["id"]


async def test_delete_not_your_submission_403(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    async with _build_client(session_factory) as client:
        mine = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        resp = await client.delete(
            f"{_sub_url(round_.id)}/{mine.json()['id']}", headers=_auth(member.id)
        )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Uniform per-player vibe stance across a player's songs (MYS-116)
# --------------------------------------------------------------------------- #


async def test_mode_stays_uniform_across_songs(session_factory, db_session):
    # Adding a second song as "vibing" flips the player's whole stance for the
    # round — both songs end up vibing.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, songs=2)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        await client.post(_sub_url(round_id), json=_body(title="one"), headers=_auth(organizer.id))
        await client.post(
            _sub_url(round_id),
            json=_body(title="two", participation_mode="vibing"),
            headers=_auth(organizer.id),
        )
        mine = await client.get(f"{_sub_url(round_id)}/mine", headers=_auth(organizer.id))
    modes = {s["participation_mode"] for s in mine.json()}
    assert modes == {"vibing"}


# --------------------------------------------------------------------------- #
# GET mine
# --------------------------------------------------------------------------- #


async def test_get_mine_returns_list(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, songs=2)
    async with _build_client(session_factory) as client:
        await client.post(_sub_url(round_.id), json=_body(title="a"), headers=_auth(organizer.id))
        await client.post(_sub_url(round_.id), json=_body(title="b"), headers=_auth(organizer.id))
        resp = await client.get(f"{_sub_url(round_.id)}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    titles = sorted(s["title"] for s in resp.json())
    assert titles == ["a", "b"]


async def test_get_mine_empty_list_when_none(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.get(f"{_sub_url(round_.id)}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 200
    assert resp.json() == []


# --------------------------------------------------------------------------- #
# GET list (reveal after close)
# --------------------------------------------------------------------------- #


async def test_list_hidden_before_close_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    async with _build_client(session_factory) as client:
        resp = await client.get(_sub_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_list_visible_after_close(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    # Seed an open round, submit, then flip to closed directly in the DB.
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    round_id = round_.id
    async with _build_client(session_factory) as client:
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
