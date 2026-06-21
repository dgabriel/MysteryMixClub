"""Tests for MYS-18 slice B: GET /rounds/:id/playlist.

The playlist reads each submission's stored platform_links (no live Odesli), so the
shared client fixture is used. Covers auth/membership gates, the open_submission
gate, anonymity, preferred-service resolution with YouTube fallback, the
empty-platforms case, and deterministic shuffling.
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
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.odesli import (
    OdesliRateLimitError,
    ResolvedSong,
    get_odesli_client,
)


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


# --------------------------------------------------------------------------- #
# YouTube playlist link (MYS-78)
# --------------------------------------------------------------------------- #


class _FakeOdesli:
    """Maps a resolvable track URL -> the ResolvedSong it returns, recording each
    resolve call so tests can assert whether the cached path skipped Odesli."""

    def __init__(self, *, by_url=None, error=None):
        self._by_url = by_url or {}
        self._error = error
        self.calls: list[str] = []

    async def resolve(self, url: str) -> ResolvedSong:
        self.calls.append(url)
        if self._error:
            raise self._error
        return self._by_url[url]


def _resolved(youtube_url: str | None) -> ResolvedSong:
    platforms = {"deezer": "https://www.deezer.com/track/123"}
    if youtube_url:
        platforms["youtube"] = youtube_url
    return ResolvedSong(title="song", artist="A", platforms=platforms)


def _client_with_odesli(session_factory, odesli) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_odesli_client] = lambda: odesli
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_youtube_playlist_url_includes_only_resolved_ids_in_order(
    session_factory, db_session
):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    # Two members so we can add three submissions total.
    for i in range(2):
        u = await _seed_user(db_session, f"m{i}@example.com")
        db_session.add(LeagueMember(league_id=round_.league_id, user_id=u.id))
    await db_session.commit()
    members = list(await db_session.scalars(select(User).where(User.email.like("m%@example.com"))))

    # Three submissions: two resolve to a YouTube id, one has no YouTube link.
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s0",
        isrc="I0",
        platform_links={
            "deezer": "https://www.deezer.com/track/0",
            "youtube": "https://music.youtube.com/search?q=s0",
        },
    )
    await _add_submission(
        db_session,
        round_.id,
        members[0].id,
        title="s1",
        isrc="I1",
        platform_links={
            "deezer": "https://www.deezer.com/track/1",
            "youtube": "https://music.youtube.com/search?q=s1",
        },
    )
    await _add_submission(
        db_session,
        round_.id,
        members[1].id,
        title="s2",
        isrc="I2",
        platform_links={
            "deezer": "https://www.deezer.com/track/2",
            "youtube": "https://music.youtube.com/search?q=s2",
        },
    )

    odesli = _FakeOdesli(
        by_url={
            "https://www.deezer.com/track/0": _resolved("https://youtube.com/watch?v=VID0"),
            "https://www.deezer.com/track/1": _resolved(None),  # no YouTube link
            "https://www.deezer.com/track/2": _resolved("https://youtube.com/watch?v=VID2"),
        }
    )

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The link contains exactly the resolved ids, in playlist (shuffled) order.
    titles = [e["title"] for e in body["entries"]]
    expected_ids = [
        vid for t, vid in ((t, {"s0": "VID0", "s1": None, "s2": "VID2"}[t]) for t in titles) if vid
    ]
    assert body["youtube_track_count"] == 2
    joined = body["youtube_playlist_url"].split("video_ids=", 1)[1].replace("%2C", ",")
    assert joined.split(",") == expected_ids


async def test_youtube_playlist_url_none_when_nothing_resolves(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s",
        isrc="I",
        platform_links={"deezer": "https://www.deezer.com/track/0"},
    )
    odesli = _FakeOdesli(by_url={"https://www.deezer.com/track/0": _resolved(None)})

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    assert body["youtube_playlist_url"] is None
    assert body["youtube_track_count"] == 0


async def test_cached_video_id_is_used_without_calling_odesli(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    db_session.add(
        Submission(
            round_id=round_.id,
            user_id=organizer.id,
            isrc="I",
            title="cached",
            artist="A",
            platform_links={"deezer": "https://www.deezer.com/track/0"},
            participation_mode="playing",
            youtube_video_id="CACHED1",
        )
    )
    await db_session.commit()

    # No mappings: if the route calls resolve(), it KeyErrors. It must not.
    odesli = _FakeOdesli(by_url={})

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    assert odesli.calls == []  # Odesli was never called for the cached track.
    assert body["youtube_track_count"] == 1
    joined = body["youtube_playlist_url"].split("video_ids=", 1)[1].replace("%2C", ",")
    assert joined == "CACHED1"


async def test_video_id_is_cached_back_onto_submission(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s",
        isrc="I",
        platform_links={"deezer": "https://www.deezer.com/track/0"},
    )
    odesli = _FakeOdesli(
        by_url={"https://www.deezer.com/track/0": _resolved("https://youtu.be/NEWVID")}
    )

    async with _client_with_odesli(session_factory, odesli) as client:
        await client.get(_url(round_.id), headers=_auth(organizer.id))

    # The resolved id is persisted; a fresh read sees it.
    sub = await db_session.scalar(select(Submission).where(Submission.round_id == round_.id))
    assert sub.youtube_video_id == "NEWVID"


async def test_odesli_failure_is_swallowed_and_endpoint_stays_200(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s",
        isrc="I",
        platform_links={"deezer": "https://www.deezer.com/track/0"},
    )
    odesli = _FakeOdesli(error=OdesliRateLimitError("slow down"))

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["youtube_playlist_url"] is None
    assert body["youtube_track_count"] == 0


def _ids_in_url(body: dict) -> list[str]:
    """The video ids actually encoded in the returned watch_videos URL."""
    return body["youtube_playlist_url"].split("video_ids=", 1)[1].replace("%2C", ",").split(",")


async def test_track_count_matches_url_when_duplicate_ids_collapse(session_factory, db_session):
    # Two distinct submissions resolving to the SAME video id must count once,
    # matching the de-duped URL (regression: count was off the raw appended list).
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    other = await _seed_user(db_session, "x@example.com")
    db_session.add(LeagueMember(league_id=round_.league_id, user_id=other.id))
    await db_session.commit()
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="a",
        isrc="I0",
        platform_links={"deezer": "https://www.deezer.com/track/0"},
    )
    await _add_submission(
        db_session,
        round_.id,
        other.id,
        title="b",
        isrc="I1",
        platform_links={"deezer": "https://www.deezer.com/track/1"},
    )
    # Both deezer tracks resolve to the identical YouTube video.
    odesli = _FakeOdesli(
        by_url={
            "https://www.deezer.com/track/0": _resolved("https://youtube.com/watch?v=SAME"),
            "https://www.deezer.com/track/1": _resolved("https://youtube.com/watch?v=SAME"),
        }
    )

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    ids = _ids_in_url(body)
    assert ids == ["SAME"]
    assert body["youtube_track_count"] == len(ids) == 1


async def test_track_count_matches_url_when_capped_at_fifty(session_factory, db_session):
    # >50 resolvable tracks: the URL caps at 50, and the count must too.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    by_url = {}
    for i in range(51):
        u = await _seed_user(db_session, f"c{i}@example.com")
        db_session.add(LeagueMember(league_id=round_.league_id, user_id=u.id))
        await db_session.commit()
        track = f"https://www.deezer.com/track/{i}"
        await _add_submission(
            db_session,
            round_.id,
            u.id,
            title=f"s{i}",
            isrc=f"I{i}",
            platform_links={"deezer": track},
        )
        by_url[track] = _resolved(f"https://youtube.com/watch?v=VID{i}")
    odesli = _FakeOdesli(by_url=by_url)

    async with _client_with_odesli(session_factory, odesli) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    ids = _ids_in_url(body)
    assert len(ids) == 50
    assert body["youtube_track_count"] == len(ids) == 50
