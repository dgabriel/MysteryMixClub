"""Tests for GET /api/v1/clubs/{club_id}/submissions (MysteryMixClub-ps1w.2).

Every song ever submitted to the club, across its CLOSED mixes only --
matches the existing per-mix visibility rule (GET /mixes/:id/submissions is
only available once a mix closes) and MYS-173 vote anonymity.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str) -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer: User) -> Club:
    club = Club(name="Test Club", organizer_id=organizer.id, total_mixes=6, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _add_member(db_session, club: Club, user: User) -> None:
    db_session.add(ClubMember(club_id=club.id, user_id=user.id))
    await db_session.commit()


async def _seed_mix(db_session, club: Club, *, number=1, state="closed", theme="theme") -> Mix:
    mix_ = Mix(club_id=club.id, mix_number=number, theme=theme, state=state)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _seed_submission(
    db_session, mix_: Mix, user: User, *, isrc="USABC1234567", source_key=None, note=None
) -> Submission:
    sub = Submission(
        mix_id=mix_.id,
        user_id=user.id,
        isrc=isrc,
        source_key=source_key,
        title="Song",
        artist="Artist",
        album="Album",
        note=note,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(
    db_session, mix_: Mix, voter: User, submission: Submission, *, weight=1
) -> None:
    db_session.add(
        Vote(mix_id=mix_.id, voter_id=voter.id, submission_id=submission.id, weight=weight)
    )
    await db_session.commit()


async def _seed_note(
    db_session, mix_: Mix, author: User, submission: Submission, body="nice"
) -> None:
    db_session.add(
        Note(mix_id=mix_.id, author_id=author.id, submission_id=submission.id, body=body)
    )
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}/submissions"


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


async def test_unauthenticated_returns_401(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)

    resp = await client.get(_url(club.id))

    assert resp.status_code == 401


async def test_unknown_club_returns_404(client, db_session):
    user = await _seed_user(db_session, "u@x.com", "User")

    resp = await client.get(_url(uuid.uuid4()), headers=_auth(user.id))

    assert resp.status_code == 404


async def test_non_member_returns_403(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    stranger = await _seed_user(db_session, "stranger@x.com", "Stranger")

    resp = await client.get(_url(club.id), headers=_auth(stranger.id))

    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Scope: closed mixes only
# --------------------------------------------------------------------------- #


async def test_empty_when_no_closed_mixes(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    open_mix = await _seed_mix(db_session, club, state="open_voting")
    await _seed_submission(db_session, open_mix, organizer)

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))

    assert resp.status_code == 200
    assert resp.json() == []


async def test_open_mix_submissions_excluded_alongside_closed(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    closed_mix = await _seed_mix(db_session, club, number=1, state="closed")
    open_mix = await _seed_mix(db_session, club, number=2, state="open_submission")
    closed_sub = await _seed_submission(db_session, closed_mix, organizer, isrc="USABC1111111")
    await _seed_submission(db_session, open_mix, organizer, isrc="USABC2222222")

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    assert len(data) == 1
    assert data[0]["submission_id"] == str(closed_sub.id)


async def test_aggregates_across_multiple_closed_mixes(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    mix1 = await _seed_mix(db_session, club, number=1, state="closed")
    mix2 = await _seed_mix(db_session, club, number=2, state="closed")
    await _seed_submission(db_session, mix1, organizer, isrc="USABC1111111")
    await _seed_submission(db_session, mix2, organizer, isrc="USABC2222222")

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    data = resp.json()

    assert resp.status_code == 200
    assert len(data) == 2
    assert {e["mix_id"] for e in data} == {str(mix1.id), str(mix2.id)}


# --------------------------------------------------------------------------- #
# Shape / content
# --------------------------------------------------------------------------- #


async def test_entry_includes_submitter_mix_and_theme(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    mix_ = await _seed_mix(db_session, club, number=3, theme="road trip", state="closed")
    sub = await _seed_submission(db_session, mix_, organizer, note="my context")

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    entry = resp.json()[0]

    assert resp.status_code == 200
    assert entry["submission_id"] == str(sub.id)
    assert entry["user_id"] == str(organizer.id)
    assert entry["submitter_display_name"] == "Org"
    assert entry["mix_id"] == str(mix_.id)
    assert entry["mix_number"] == 3
    assert entry["theme"] == "road trip"
    assert entry["submitter_note"] == "my context"


async def test_source_only_submission_included(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    mix_ = await _seed_mix(db_session, club, state="closed")
    await _seed_submission(db_session, mix_, organizer, isrc=None, source_key="youtube:PRpiBpDy7MQ")

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    entry = resp.json()[0]

    assert resp.status_code == 200
    assert entry["isrc"] is None
    assert entry["source"] == "youtube"
    assert entry["source_url"] is not None


async def test_voters_revealed_since_mix_is_closed(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    voter = await _seed_user(db_session, "voter@x.com", "Voter")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club, voter)
    mix_ = await _seed_mix(db_session, club, state="closed")
    sub = await _seed_submission(db_session, mix_, organizer)
    await _seed_vote(db_session, mix_, voter, sub, weight=2)

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    entry = resp.json()[0]

    assert resp.status_code == 200
    assert entry["vote_count"] == 2
    assert len(entry["voters"]) == 1
    assert entry["voters"][0]["display_name"] == "Voter"
    assert entry["voters"][0]["weight"] == 2


async def test_all_notes_revealed_since_mix_is_closed(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    other = await _seed_user(db_session, "other@x.com", "Other")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club, other)
    mix_ = await _seed_mix(db_session, club, state="closed")
    sub = await _seed_submission(db_session, mix_, organizer)
    await _seed_note(db_session, mix_, other, sub, body="great pick")

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    entry = resp.json()[0]

    assert resp.status_code == 200
    assert len(entry["notes"]) == 1
    assert entry["notes"][0]["body"] == "great pick"
    assert entry["notes"][0]["author_display_name"] == "Other"


async def test_ordered_newest_submission_first(client, db_session):
    organizer = await _seed_user(db_session, "org@x.com", "Org")
    club = await _seed_club(db_session, organizer)
    mix1 = await _seed_mix(db_session, club, number=1, state="closed")
    mix2 = await _seed_mix(db_session, club, number=2, state="closed")
    first = await _seed_submission(db_session, mix1, organizer, isrc="USABC1111111")
    second = await _seed_submission(db_session, mix2, organizer, isrc="USABC2222222")
    now = datetime.now(timezone.utc)
    first.created_at = now - timedelta(minutes=1)
    second.created_at = now
    await db_session.commit()

    resp = await client.get(_url(club.id), headers=_auth(organizer.id))
    ids = [e["submission_id"] for e in resp.json()]

    assert resp.status_code == 200
    assert ids == [str(second.id), str(first.id)]
