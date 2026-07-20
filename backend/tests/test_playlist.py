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
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.youtube_resolver import get_youtube_resolver


def _links(*platforms: str) -> dict:
    return {p: f"https://{p}/x" for p in platforms}


async def _seed_user(db_session, email: str, *, preferred: str | None = None) -> User:
    user = User(email=email, display_name="U", preferred_service=preferred)
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
    db_session,
    round_id,
    user_id,
    *,
    title,
    isrc,
    platform_links,
    mode="playing",
    youtube_video_id=None,
    source_key=None,
):
    db_session.add(
        Submission(
            round_id=round_id,
            user_id=user_id,
            isrc=isrc,
            source_key=source_key,
            title=title,
            artist="A",
            platform_links=platform_links,
            participation_mode=mode,
            youtube_video_id=youtube_video_id,
        )
    )
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(round_id) -> str:
    return f"/api/v1/mixes/{round_id}/playlist"


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
    # A normal catalog track has no source-only identity (MYS-201 Phase 2).
    assert entry["source"] is None
    assert entry["source_url"] is None
    # No submitter identity is leaked during voting.
    assert "user_id" not in entry
    assert "submitter" not in entry
    # Vibing is private: the playlist must not reveal which songs are vibers'
    # (MYS-112).
    assert "participation_mode" not in entry


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


async def test_playlist_carries_bandcamp_track_id_key_without_leaking_as_url(client, db_session):
    # The reserved non-URL bandcampTrackId key (MYS-201/204) rides along in the
    # exposed platforms dict, but must never be chosen as a playable URL: with a
    # preferred service and youtube both present, the real link still wins.
    organizer = await _seed_user(db_session, "o@example.com", preferred="deezer")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="bc",
        isrc="I1",
        platform_links={
            "deezer": "https://deezer/x",
            "youtube": "https://youtube/x",
            "bandcampTrackId": "12345",
        },
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    entry = resp.json()["entries"][0]
    assert entry["platforms"]["bandcampTrackId"] == "12345"
    assert entry["preferred_url"] == "https://deezer/x"


async def test_playlist_bandcamp_track_id_not_chosen_as_fallback_url(client, db_session):
    # No preference and no youtube: the fallback takes the FIRST real link, never
    # the trailing non-URL id (it is always merged last into platform_links).
    organizer = await _seed_user(db_session, "o@example.com", preferred=None)
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="bc",
        isrc="I1",
        platform_links={
            "bandcamp": "https://x.bandcamp.com/track/y",
            "bandcampTrackId": "12345",
        },
    )
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    entry = resp.json()["entries"][0]
    assert entry["preferred_url"] == "https://x.bandcamp.com/track/y"
    assert entry["platforms"]["bandcampTrackId"] == "12345"


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


class _FakeYouTube:
    """Resolves a song -> video id by ``(title, artist)``, recording each call so
    tests can assert the resolver is skipped for already-cached submissions.
    ``error`` simulates an upstream failure that the resolver itself swallows to
    None — here we return None to mirror its best-effort contract."""

    def __init__(self, *, by_title=None, error=False):
        self._by_title = by_title or {}
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        self.calls.append((title, artist))
        if self._error:
            return None
        return self._by_title.get(title)


def _client_with_youtube(session_factory, youtube) -> AsyncClient:
    app = create_app()

    async def override_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_youtube_resolver] = lambda: youtube
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _ids_in_url(body: dict) -> list[str]:
    """The video ids actually encoded in the returned watch_videos URL."""
    return body["youtube_playlist_url"].split("video_ids=", 1)[1].replace("%2C", ",").split(",")


async def test_youtube_playlist_url_includes_only_stored_ids_in_order(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    for i in range(2):
        u = await _seed_user(db_session, f"m{i}@example.com")
        db_session.add(LeagueMember(league_id=round_.league_id, user_id=u.id))
    await db_session.commit()
    members = list(await db_session.scalars(select(User).where(User.email.like("m%@example.com"))))

    # Three submissions: two carry a stored YouTube id, one has none.
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s0",
        isrc="I0",
        platform_links=_links("deezer"),
        youtube_video_id="VID0",
    )
    await _add_submission(
        db_session,
        round_.id,
        members[0].id,
        title="s1",
        isrc="I1",
        platform_links=_links("deezer"),
        youtube_video_id=None,
    )
    await _add_submission(
        db_session,
        round_.id,
        members[1].id,
        title="s2",
        isrc="I2",
        platform_links=_links("deezer"),
        youtube_video_id="VID2",
    )

    # The resolver returns nothing, so the null submission stays out of the link.
    youtube = _FakeYouTube(by_title={})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The link contains exactly the stored ids, in playlist (shuffled) order.
    titles = [e["title"] for e in body["entries"]]
    expected_ids = [
        vid for t, vid in ((t, {"s0": "VID0", "s1": None, "s2": "VID2"}[t]) for t in titles) if vid
    ]
    assert body["youtube_track_count"] == 2
    assert _ids_in_url(body) == expected_ids


async def test_youtube_playlist_url_none_when_nothing_resolves(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s",
        isrc="I",
        platform_links=_links("deezer"),
        youtube_video_id=None,
    )
    # No stored id, and the resolver finds nothing on backfill.
    youtube = _FakeYouTube(by_title={})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    assert body["youtube_playlist_url"] is None
    assert body["youtube_track_count"] == 0


async def test_stored_id_is_used_without_calling_resolver(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="cached",
        isrc="I",
        platform_links=_links("deezer"),
        youtube_video_id="CACHED1",
    )
    # If the route resolved a cached submission, calls would be non-empty.
    youtube = _FakeYouTube(by_title={"cached": "SHOULD_NOT_BE_USED"})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    assert youtube.calls == []  # resolver never touched for a cached track
    assert body["youtube_track_count"] == 1
    assert _ids_in_url(body) == ["CACHED1"]


async def test_lazy_backfill_resolves_and_caches_null_id(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="needs backfill",
        isrc="I",
        platform_links=_links("deezer"),
        youtube_video_id=None,
    )
    youtube = _FakeYouTube(by_title={"needs backfill": "NEWVID"})

    async with _client_with_youtube(session_factory, youtube) as client:
        first = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = first.json()
    assert _ids_in_url(body) == ["NEWVID"]
    assert body["youtube_track_count"] == 1
    assert youtube.calls == [("needs backfill", "A")]  # resolved once

    # The id is cached back; a fresh read sees it without resolving again.
    sub = await db_session.scalar(select(Submission).where(Submission.round_id == round_.id))
    assert sub.youtube_video_id == "NEWVID"

    async with _client_with_youtube(session_factory, youtube) as client:
        await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert youtube.calls == [("needs backfill", "A")]  # not called a second time


async def test_resolver_failure_is_swallowed_and_endpoint_stays_200(session_factory, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="s",
        isrc="I",
        platform_links=_links("deezer"),
        youtube_video_id=None,
    )
    youtube = _FakeYouTube(error=True)

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["youtube_playlist_url"] is None
    assert body["youtube_track_count"] == 0


async def test_track_count_matches_url_when_duplicate_ids_collapse(session_factory, db_session):
    # Two distinct submissions with the SAME stored video id must count once,
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
        platform_links=_links("deezer"),
        youtube_video_id="SAME",
    )
    await _add_submission(
        db_session,
        round_.id,
        other.id,
        title="b",
        isrc="I1",
        platform_links=_links("deezer"),
        youtube_video_id="SAME",
    )
    youtube = _FakeYouTube(by_title={})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    ids = _ids_in_url(body)
    assert ids == ["SAME"]
    assert body["youtube_track_count"] == len(ids) == 1


async def test_track_count_matches_url_when_capped_at_fifty(session_factory, db_session):
    # >50 stored ids: the URL caps at 50, and the count must too.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    for i in range(51):
        u = await _seed_user(db_session, f"c{i}@example.com")
        db_session.add(LeagueMember(league_id=round_.league_id, user_id=u.id))
        await db_session.commit()
        await _add_submission(
            db_session,
            round_.id,
            u.id,
            title=f"s{i}",
            isrc=f"I{i}",
            platform_links=_links("deezer"),
            youtube_video_id=f"VID{i}",
        )
    youtube = _FakeYouTube(by_title={})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    ids = _ids_in_url(body)
    assert len(ids) == 50
    assert body["youtube_track_count"] == len(ids) == 50


# --------------------------------------------------------------------------- #
# Voting progress (MYS-102)
# --------------------------------------------------------------------------- #


async def _submission_id(db_session, round_id, user_id):
    return await db_session.scalar(
        select(Submission.id).where(Submission.round_id == round_id, Submission.user_id == user_id)
    )


async def test_playlist_reports_voting_progress(client, db_session):
    """X of Y voted-or-noted · Z just vibing.

    Four playing submitters (Y=4): one votes, one leaves a note (acted X=2),
    two do nothing. One vibing submitter (Z=1) sits voting out.
    """
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    voter = await _seed_user(db_session, "voter@example.com")
    noter = await _seed_user(db_session, "noter@example.com")
    idle = await _seed_user(db_session, "idle@example.com")
    viber = await _seed_user(db_session, "vibe@example.com")

    await _add_submission(
        db_session, round_.id, organizer.id, title="org", isrc="IO", platform_links=_links("deezer")
    )
    await _add_submission(
        db_session, round_.id, voter.id, title="v", isrc="IV", platform_links=_links("deezer")
    )
    await _add_submission(
        db_session, round_.id, noter.id, title="n", isrc="IN", platform_links=_links("deezer")
    )
    await _add_submission(
        db_session, round_.id, idle.id, title="i", isrc="II", platform_links=_links("deezer")
    )
    await _add_submission(
        db_session,
        round_.id,
        viber.id,
        title="z",
        isrc="IZ",
        platform_links=_links("deezer"),
        mode="vibing",
    )

    org_sub = await _submission_id(db_session, round_.id, organizer.id)
    # voter votes for the organizer's song; noter leaves a note on it.
    db_session.add(Vote(round_id=round_.id, voter_id=voter.id, submission_id=org_sub))
    db_session.add(Note(round_id=round_.id, author_id=noter.id, submission_id=org_sub, body="nice"))
    await db_session.commit()

    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["voting_eligible"] == 4  # four playing submitters
    assert body["voting_acted"] == 2  # voter + noter
    assert body["vibing_count"] == 1


async def test_playlist_vibing_noter_not_counted_as_acted(client, db_session):
    """A vibing player who leaves a note is reported under Z, never inside X/Y."""
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    viber = await _seed_user(db_session, "vibe@example.com")

    await _add_submission(
        db_session, round_.id, organizer.id, title="org", isrc="IO", platform_links=_links("deezer")
    )
    await _add_submission(
        db_session,
        round_.id,
        viber.id,
        title="z",
        isrc="IZ",
        platform_links=_links("deezer"),
        mode="vibing",
    )
    org_sub = await _submission_id(db_session, round_.id, organizer.id)
    # The vibing player notes on the organizer's song — counts as vibing, not acted.
    db_session.add(
        Note(round_id=round_.id, author_id=viber.id, submission_id=org_sub, body="vibes")
    )
    await db_session.commit()

    body = (await client.get(_url(round_.id), headers=_auth(organizer.id))).json()
    assert body["voting_eligible"] == 1  # only the organizer is playing
    assert body["voting_acted"] == 0  # organizer didn't act; vibing noter excluded
    assert body["vibing_count"] == 1


# --------------------------------------------------------------------------- #
# MYS-201: source-only tracks in the round playlist
# --------------------------------------------------------------------------- #


async def test_bandcamp_source_only_skips_youtube_backfill(session_factory, db_session):
    # A bandcamp source_key row must never be fuzzy-resolved to a *guessed* video:
    # it carries no youtube_video_id and sits out the YouTube playlist entirely.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="bandcamp track",
        isrc=None,
        source_key="bandcamp:coolband/bandcamp-track",
        platform_links=_links("bandcamp"),
        youtube_video_id=None,
    )
    # The resolver WOULD return an id if consulted — asserting it never is.
    youtube = _FakeYouTube(by_title={"bandcamp track": "GUESSVID1234"})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert youtube.calls == []  # never fuzzy-resolved
    assert body["youtube_playlist_url"] is None
    assert body["youtube_track_count"] == 0
    # The entry is still present, with a null ISRC, and carries its source so the
    # client can badge it "Bandcamp only" and link out (MYS-201 Phase 2).
    assert [e["title"] for e in body["entries"]] == ["bandcamp track"]
    entry = body["entries"][0]
    assert entry["isrc"] is None
    assert entry["source"] == "bandcamp"
    assert entry["source_url"] == "https://coolband.bandcamp.com/track/bandcamp-track"


async def test_youtube_source_only_uses_stored_id_without_backfill(session_factory, db_session):
    # A youtube source_key row already carries its exact id from submit time; the
    # playlist uses it directly, never re-resolving.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _add_submission(
        db_session,
        round_.id,
        organizer.id,
        title="yt only",
        isrc=None,
        source_key="youtube:PRpiBpDy7MQ",
        platform_links=_links("youtube"),
        youtube_video_id="PRpiBpDy7MQ",
    )
    youtube = _FakeYouTube(by_title={"yt only": "SHOULD_NOT_USE"})

    async with _client_with_youtube(session_factory, youtube) as client:
        resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    body = resp.json()
    assert youtube.calls == []  # exact stored id, no backfill
    assert body["youtube_track_count"] == 1
    assert _ids_in_url(body) == ["PRpiBpDy7MQ"]
    entry = body["entries"][0]
    assert entry["isrc"] is None
    assert entry["source"] == "youtube"
    assert entry["source_url"] == "https://www.youtube.com/watch?v=PRpiBpDy7MQ"
