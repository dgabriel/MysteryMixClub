"""Tests for MYS-51 + MYS-116: song submission endpoints.

The link assembler is overridden with a fake (no live HTTP). Covers
auth/membership gates, the round-state gate, the happy path + platform_links
persistence, degraded-links behaviour, the per-league songs_per_submission cap
(add up to the cap, then 409), edit (PATCH) + delete of individual songs,
uniform per-player vibe stance across a player's songs, participation-mode
defaulting, and the read endpoints (mine as a list, and the reveal-after-close
list gate).
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import create_access_token
from app.db.session import get_db
from app.main import create_app
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.services.song_links import SongLinkAssembler, get_link_assembler
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

    async def assemble(
        self, title, artist=None, isrc=None, *, youtube_video_id=None
    ) -> dict[str, str]:
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
) -> Mix:
    # `vibe` seeds the organizer's per-league vibe_mode, so their submission
    # defaults to that mode (MYS-112). `songs` is the per-league songs_per_submission
    # cap (MYS-116; default 1 = classic one-song behaviour).
    league = Club(
        name="L",
        organizer_id=organizer.id,
        total_mixes=3,
        votes_per_player=3,
        songs_per_submission=songs,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=organizer.id, vibe_mode=vibe))
    round_ = Mix(club_id=league.id, mix_number=1, theme="late summer", state=state)
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(ClubMember(club_id=league_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _body(**over) -> dict:
    title = over.get("title", "bad guy")
    body = {
        "isrc": f"USABC{abs(hash(title)):07d}",
        "title": "bad guy",
        "artist": "Billie Eilish",
    }
    body.update(over)
    return body


def _sub_url(round_id) -> str:
    return f"/api/v1/mixes/{round_id}/submissions"


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
    assert body["isrc"] == _body(note="a quiet banger")["isrc"]
    assert body["title"] == "bad guy"
    assert body["participation_mode"] == "playing"
    assert body["note"] == "a quiet banger"
    # platform_links are stored server-side (not exposed in the response).
    assert "platform_links" not in body
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
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
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
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
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
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
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
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
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
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
        select(func.count()).select_from(Submission).where(Submission.mix_id == round_id)
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
    await _add_member(db_session, round_.club_id, member)
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
        db_round = await db_session.scalar(select(Mix).where(Mix.id == round_id))
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
    await _add_member(db_session, round_.club_id, member)
    async with _build_client(session_factory) as client:
        mine = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        resp = await client.delete(
            f"{_sub_url(round_.id)}/{mine.json()['id']}", headers=_auth(member.id)
        )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# PATCH note — edit only the submitter note without replacing the track (MYS-150)
# --------------------------------------------------------------------------- #


async def test_update_note_sets_and_clears(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        sub = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        sub_id = sub.json()["id"]
        # Set a note, leaving the track untouched.
        set_resp = await client.patch(
            f"{_sub_url(round_.id)}/{sub_id}/note",
            json={"note": "a quiet banger"},
            headers=_auth(organizer.id),
        )
        assert set_resp.status_code == 200, set_resp.text
        assert set_resp.json()["note"] == "a quiet banger"
        assert set_resp.json()["title"] == sub.json()["title"]
        # Clearing with null removes it.
        clear_resp = await client.patch(
            f"{_sub_url(round_.id)}/{sub_id}/note",
            json={"note": None},
            headers=_auth(organizer.id),
        )
        assert clear_resp.status_code == 200, clear_resp.text
        assert clear_resp.json()["note"] is None


async def test_update_note_not_your_submission_403(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.club_id, member)
    async with _build_client(session_factory) as client:
        sub = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        resp = await client.patch(
            f"{_sub_url(round_.id)}/{sub.json()['id']}/note",
            json={"note": "not mine"},
            headers=_auth(member.id),
        )
    assert resp.status_code == 403


async def test_update_note_when_not_open_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        sub = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        sub_id = sub.json()["id"]
        # Move the round past submissions.
        round_.state = "open_voting"
        await db_session.commit()
        resp = await client.patch(
            f"{_sub_url(round_.id)}/{sub_id}/note",
            json={"note": "too late"},
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 409


async def test_update_note_too_long_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        sub = await client.post(_sub_url(round_.id), json=_body(), headers=_auth(organizer.id))
        resp = await client.patch(
            f"{_sub_url(round_.id)}/{sub.json()['id']}/note",
            json={"note": "x" * 281},
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 422


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
    await _add_member(db_session, round_.club_id, member)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
        await client.post(
            _sub_url(round_id), json=_body(title="member pick"), headers=_auth(member.id)
        )
        # Close the round (membership read still allowed).
        db_round = await db_session.scalar(select(Mix).where(Mix.id == round_id))
        db_round.state = "closed"
        await db_session.commit()
        resp = await client.get(_sub_url(round_id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    titles = sorted(s["title"] for s in resp.json())
    assert titles == ["bad guy", "member pick"]


# --------------------------------------------------------------------------- #
# MYS-144: concurrent submissions must not exceed the per-league cap
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# MYS-201: source-only submissions (no ISRC — Bandcamp/YouTube-only tracks)
# --------------------------------------------------------------------------- #


def _no_http_assembler() -> SongLinkAssembler:
    """The real link assembler wired to a transport that fails on any request.

    A source-only track must be linked with NO fuzzy lookup, so a correct
    ``assemble(..., fuzzy=False)`` makes zero HTTP calls — this asserts that by
    blowing up if any is attempted, while still returning the real exact links."""

    def factory() -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError(f"no HTTP expected for a source-only track, got {request.url}")

        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return SongLinkAssembler(client_factory=factory)


class _BoomYouTube:
    """A YouTube resolver that fails if consulted — a source-only submission must
    never fuzzy-resolve a video id (that is the isrc/catalog path only)."""

    async def video_id_for(self, title, artist=None) -> str | None:  # pragma: no cover
        raise AssertionError("YouTube resolver must not be called for a source-only track")


def _source_body(source_key: str, **over) -> dict:
    body = {"source_key": source_key, "title": "obscure", "artist": "Some Artist"}
    body.update(over)
    return body


async def _seed_second_round(db_session, league_id: uuid.UUID, *, number: int = 2) -> Mix:
    round_ = Mix(club_id=league_id, mix_number=number, theme="t2", state="open_submission")
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def test_submit_neither_isrc_nor_source_key_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    body = {"title": "no identity", "artist": "A"}
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=body, headers=_auth(organizer.id))
    assert resp.status_code == 422


async def test_submit_both_isrc_and_source_key_422(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    body = _body(source_key="youtube:PRpiBpDy7MQ")
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_.id), json=body, headers=_auth(organizer.id))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "bad_key",
    [
        "not a key",
        "spotify:3PfIrDoz19",  # wrong source prefix
        "youtube:short",  # wrong length id
        "youtube:toolongvideoid",  # too long
        "bandcamp:CoolBand/song",  # uppercase artist slug
        "bandcamp:../etc/passwd",  # path traversal
        "bandcamp:artist",  # missing track segment
    ],
)
async def test_submit_malformed_source_key_422(session_factory, db_session, bad_key):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_source_body(bad_key), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


async def test_submit_bandcamp_source_only_happy_path(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        resp = await client.post(
            _sub_url(round_id),
            json=_source_body("bandcamp:coolband/song-title", note="only on bandcamp"),
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Response carries the source identity, never an ISRC.
    assert body["isrc"] is None
    assert body["source"] == "bandcamp"
    assert body["source_url"] == "https://coolband.bandcamp.com/track/song-title"
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
    assert stored.source_key == "bandcamp:coolband/song-title"
    assert stored.isrc is None
    # The stored Bandcamp link is the exact reconstructed track page, and YouTube
    # is only a search deep link (a bandcamp track never gets a guessed video).
    assert stored.platform_links["bandcamp"] == "https://coolband.bandcamp.com/track/song-title"
    assert stored.platform_links["youtube"].startswith("https://www.youtube.com/results?")
    assert stored.youtube_video_id is None


async def test_submit_youtube_source_only_uses_exact_video_id(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        resp = await client.post(
            _sub_url(round_id),
            json=_source_body("youtube:PRpiBpDy7MQ"),
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["isrc"] is None
    assert body["source"] == "youtube"
    assert body["source_url"] == "https://www.youtube.com/watch?v=PRpiBpDy7MQ"
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
    assert stored.source_key == "youtube:PRpiBpDy7MQ"
    # The exact submitted video id drives the watch links and is cached — no search.
    assert stored.youtube_video_id == "PRpiBpDy7MQ"
    assert stored.platform_links["youtube"] == "https://www.youtube.com/watch?v=PRpiBpDy7MQ"
    assert stored.platform_links["youtubeMusic"] == "https://music.youtube.com/watch?v=PRpiBpDy7MQ"


async def test_duplicate_source_key_within_mix_409(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.club_id, member)
    key = "bandcamp:coolband/song-title"
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        first = await client.post(
            _sub_url(round_.id), json=_source_body(key), headers=_auth(organizer.id)
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            _sub_url(round_.id), json=_source_body(key), headers=_auth(member.id)
        )
    assert second.status_code == 409, second.text
    assert "already in this mystery mix" in second.json()["detail"]


async def test_distinct_source_keys_do_not_collide(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.club_id, member)
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        a = await client.post(
            _sub_url(round_.id),
            json=_source_body("bandcamp:coolband/song-title"),
            headers=_auth(organizer.id),
        )
        b = await client.post(
            _sub_url(round_.id),
            json=_source_body("bandcamp:coolband/other-song"),
            headers=_auth(member.id),
        )
    assert a.status_code == 201, a.text
    assert b.status_code == 201, b.text


async def test_source_key_repeat_across_prior_mix_flags_but_allows(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round1 = await _seed_league_with_round(db_session, organizer)
    round2 = await _seed_second_round(db_session, round1.club_id)
    key = "youtube:PRpiBpDy7MQ"
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        first = await client.post(
            _sub_url(round1.id), json=_source_body(key), headers=_auth(organizer.id)
        )
        assert first.status_code == 201, first.text
        assert first.json()["league_previously_submitted"] is False
        repeat = await client.post(
            _sub_url(round2.id), json=_source_body(key), headers=_auth(organizer.id)
        )
    # A repeat in a later mix of the same club is allowed, but flagged.
    assert repeat.status_code == 201, repeat.text
    assert repeat.json()["league_previously_submitted"] is True


# --------------------------------------------------------------------------- #
# MYS-201: Bandcamp numeric track id rides along in platform_links (MYS-204)
# --------------------------------------------------------------------------- #


async def test_submit_persists_bandcamp_track_id_under_reserved_key(session_factory, db_session):
    # A catalog track (isrc) that came from a Bandcamp paste carries the id back;
    # it persists under the reserved non-URL key alongside the real platform links.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_id), json=_body(bandcamp_track_id="12345"), headers=_auth(organizer.id)
        )
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
    assert stored.platform_links == {**_LINKS, "bandcampTrackId": "12345"}


async def test_submit_source_only_bandcamp_track_id_rides_along(session_factory, db_session):
    # Source-only Bandcamp track: the id persists next to the exact source links.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(
        session_factory, assembler=_no_http_assembler(), youtube=_BoomYouTube()
    ) as client:
        resp = await client.post(
            _sub_url(round_id),
            json=_source_body("bandcamp:coolband/song-title", bandcamp_track_id="98765"),
            headers=_auth(organizer.id),
        )
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
    assert stored.platform_links["bandcampTrackId"] == "98765"
    # The real exact links are untouched by the extra key.
    assert stored.platform_links["bandcamp"] == "https://coolband.bandcamp.com/track/song-title"


async def test_submit_without_bandcamp_track_id_adds_no_key(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    async with _build_client(session_factory) as client:
        resp = await client.post(_sub_url(round_id), json=_body(), headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    db_session.expire_all()
    stored = await db_session.scalar(select(Submission).where(Submission.mix_id == round_id))
    assert "bandcampTrackId" not in stored.platform_links
    assert stored.platform_links == _LINKS


@pytest.mark.parametrize(
    "bad_id",
    [
        "abc",  # non-digit
        "12 34",  # embedded whitespace
        "12.5",  # non-digit separator
        "1" * 21,  # over the 20-digit bound
        "",  # empty
    ],
)
async def test_submit_malformed_bandcamp_track_id_422(session_factory, db_session, bad_id):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    async with _build_client(session_factory) as client:
        resp = await client.post(
            _sub_url(round_.id), json=_body(bandcamp_track_id=bad_id), headers=_auth(organizer.id)
        )
    assert resp.status_code == 422, resp.text


async def test_concurrent_submit_at_cap_1_produces_exactly_one_submission(
    session_factory, db_session
):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, songs=1)
    round_id = round_.id
    organizer_id = organizer.id

    async with _build_client(session_factory) as client:
        resp1, resp2 = await asyncio.gather(
            client.post(
                _sub_url(round_id),
                json=_body(title="song a", isrc="USAAA0000001"),
                headers=_auth(organizer_id),
            ),
            client.post(
                _sub_url(round_id),
                json=_body(title="song b", isrc="USAAA0000002"),
                headers=_auth(organizer_id),
            ),
        )

    statuses = sorted([resp1.status_code, resp2.status_code])
    assert statuses == [201, 409], f"expected one success and one cap rejection, got {statuses}"

    db_session.expire_all()
    count = await db_session.scalar(
        select(func.count()).select_from(Submission).where(Submission.mix_id == round_id)
    )
    assert count == 1, "concurrent submissions must not exceed the cap"
