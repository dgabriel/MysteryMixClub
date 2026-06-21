"""Tests for MYS-18 slice B: GET /rounds/:id/playlist.

The playlist reads each submission's stored platform_links (no live Odesli), so the
shared client fixture is used. Covers auth/membership gates, the open_submission
gate, anonymity, preferred-service resolution with YouTube fallback, the
empty-platforms case, and deterministic shuffling.
"""

import uuid

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User


def _links(*platforms: str) -> dict:
    return {p: f"https://{p}/x" for p in platforms}


async def _seed_user(db_session, email: str, *, preferred: str | None = None) -> User:
    user = User(email=email, display_name="U", default_vibe_mode=False, preferred_service=preferred)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_round(db_session, organizer: User, *, state: str = "open_voting") -> Round:
    league = League(name="L", organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(league_id=league.id, round_number=1, theme="t", state=state)
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _add_submission(
    db_session, round_id, user_id, *, title, isrc, platform_links, mode="playing"
):
    db_session.add(
        Submission(
            round_id=round_id,
            user_id=user_id,
            isrc=isrc,
            title=title,
            artist="A",
            platform_links=platform_links,
            participation_mode=mode,
        )
    )
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/playlist"


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


async def test_playlist_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.get(_url(round_.id))
    assert resp.status_code == 401


async def test_playlist_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_round(db_session, organizer)
    resp = await client.get(_url(round_.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_playlist_hidden_during_submission(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer, state="open_submission")
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409


# --------------------------------------------------------------------------- #
# Content
# --------------------------------------------------------------------------- #


async def test_playlist_entries_are_anonymous(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="bad guy",
        isrc="I1",
        platform_links=_links("deezer"),
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["theme"] == "t"
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["title"] == "bad guy"
    # No submitter identity is leaked during voting.
    assert "user_id" not in entry
    assert "submitter" not in entry


async def test_playlist_marks_callers_own_submission(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    other = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_round(db_session, organizer)
    db_session.add(LeagueMember(league_id=round_.league_id, user_id=other.id))
    await db_session.commit()
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="mine",
        isrc="I1",
        platform_links=_links("deezer"),
    )
    await _add_submission(
        db_session, round_.id, other.id, title="theirs", isrc="I2", platform_links=_links("deezer")
    )

    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    by_title = {e["title"]: e for e in resp.json()["entries"]}
    # Only the caller's own pick is flagged; no other submitter is revealed.
    assert by_title["mine"]["is_own"] is True
    assert by_title["theirs"]["is_own"] is False
    assert "user_id" not in by_title["theirs"]


async def test_preferred_service_link_is_chosen(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", preferred="deezer")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="x",
        isrc="I1",
        platform_links=_links("spotify", "deezer", "youtube"),
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    entry = resp.json()["entries"][0]
    assert entry["preferred_url"] == "https://deezer/x"
    assert set(entry["platforms"]) == {"spotify", "deezer", "youtube"}


async def test_youtube_fallback_when_no_preference(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", preferred=None)
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="x",
        isrc="I1",
        platform_links=_links("spotify", "youtube"),
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.json()["entries"][0]["preferred_url"] == "https://youtube/x"


async def test_preferred_url_none_when_no_platforms(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session, round_.id, organizer.id, title="x", isrc="I1", platform_links=None
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    entry = resp.json()["entries"][0]
    assert entry["platforms"] == {}
    assert entry["preferred_url"] is None


async def test_playlist_shuffle_is_deterministic(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    for i in range(6):
        u = await _seed_user(db_session, f"u{i}@example.com")
        db_session.add(LeagueMember(league_id=round_.league_id, user_id=u.id))
        await db_session.commit()
        await _add_submission(
            db_session,
            round_.id,
            u.id,
            title=f"song {i}",
            isrc=f"I{i}",
            platform_links=_links("youtube"),
        )

    first = await client.get(_url(round_.id), headers=_auth(organizer.id))
    second = await client.get(_url(round_.id), headers=_auth(organizer.id))
    order1 = [e["title"] for e in first.json()["entries"]]
    order2 = [e["title"] for e in second.json()["entries"]]
    assert order1 == order2  # stable per round
    assert sorted(order1) == [f"song {i}" for i in range(6)]  # all present
