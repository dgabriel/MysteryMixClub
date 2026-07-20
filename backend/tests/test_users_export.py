"""Tests for MYS-185: GET /users/me/export (GDPR Art. 15/20 right of access).

Read-only counterpart to the hard-purge cascade (test_purge_accounts.py):
returns the caller's own profile, submissions, votes, notes, and club
memberships as a JSON dump. Never another user's data.
"""

import uuid
from datetime import datetime, timezone

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.note import Note
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

EXPORT_URL = "/api/v1/users/me/export"


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer_id, *, name="L") -> Club:
    club = Club(name=name, organizer_id=organizer_id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer_id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_mix(db_session, club_id, *, number=1) -> Mix:
    mix_ = Mix(
        club_id=club_id,
        mix_number=number,
        theme="a theme",
        state="closed",
        votes_per_player=3,
    )
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _seed_submission(
    db_session, mix_id, user_id, *, isrc="USABC1234567", source_key=None
) -> Submission:
    sub = Submission(
        mix_id=mix_id,
        user_id=user_id,
        isrc=isrc,
        source_key=source_key,
        title="song",
        artist="Artist",
        note="context",
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, mix_id, voter_id, submission_id) -> Vote:
    vote = Vote(mix_id=mix_id, voter_id=voter_id, submission_id=submission_id)
    db_session.add(vote)
    await db_session.commit()
    await db_session.refresh(vote)
    return vote


async def _seed_note(db_session, mix_id, author_id, submission_id, body="nice") -> Note:
    note = Note(mix_id=mix_id, author_id=author_id, submission_id=submission_id, body=body)
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)
    return note


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


async def test_export_requires_auth(client, db_session):
    resp = await client.get(EXPORT_URL)
    assert resp.status_code == 401


async def test_export_includes_own_profile(client, db_session):
    user = await _seed_user(db_session, "alice@example.com", name="Alice")

    resp = await client.get(EXPORT_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile"]["email"] == "alice@example.com"
    assert body["profile"]["display_name"] == "Alice"
    assert datetime.fromisoformat(body["exported_at"]) <= datetime.now(timezone.utc)


async def test_export_empty_for_a_user_with_no_activity(client, db_session):
    user = await _seed_user(db_session, "empty@example.com")

    resp = await client.get(EXPORT_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submissions"] == []
    assert body["votes"] == []
    assert body["notes"] == []
    assert body["club_memberships"] == []


async def test_export_includes_own_submission(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com", name="Org")
    club = await _seed_club(db_session, organizer.id)
    mix_ = await _seed_mix(db_session, club.id)
    submission = await _seed_submission(db_session, mix_.id, organizer.id)

    resp = await client.get(EXPORT_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    submissions = resp.json()["submissions"]
    assert len(submissions) == 1
    assert submissions[0]["id"] == str(submission.id)
    assert submissions[0]["title"] == "song"
    assert submissions[0]["note"] == "context"
    # A catalog track carries its ISRC and no source_key (MYS-201).
    assert submissions[0]["isrc"] == "USABC1234567"
    assert submissions[0]["source_key"] is None


async def test_export_includes_source_only_submission(client, db_session):
    # A source-only submission (Bandcamp/YouTube, no ISRC) exports its source_key
    # and a null isrc, rather than being dropped or erroring (MYS-201).
    organizer = await _seed_user(db_session, "src@example.com", name="Src")
    club = await _seed_club(db_session, organizer.id)
    mix_ = await _seed_mix(db_session, club.id)
    await _seed_submission(
        db_session, mix_.id, organizer.id, isrc=None, source_key="youtube:PRpiBpDy7MQ"
    )

    resp = await client.get(EXPORT_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    submissions = resp.json()["submissions"]
    assert len(submissions) == 1
    assert submissions[0]["isrc"] is None
    assert submissions[0]["source_key"] == "youtube:PRpiBpDy7MQ"


async def test_export_includes_own_vote_and_note(client, db_session):
    organizer = await _seed_user(db_session, "org2@example.com", name="Org2")
    voter = await _seed_user(db_session, "voter@example.com", name="Voter")
    club = await _seed_club(db_session, organizer.id)
    db_session.add(ClubMember(club_id=club.id, user_id=voter.id))
    await db_session.commit()
    mix_ = await _seed_mix(db_session, club.id)
    submission = await _seed_submission(db_session, mix_.id, organizer.id)
    vote = await _seed_vote(db_session, mix_.id, voter.id, submission.id)
    note = await _seed_note(db_session, mix_.id, voter.id, submission.id, body="great pick")

    resp = await client.get(EXPORT_URL, headers=_auth_header(voter.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [v["id"] for v in body["votes"]] == [str(vote.id)]
    assert [n["id"] for n in body["notes"]] == [str(note.id)]
    assert body["notes"][0]["body"] == "great pick"
    # The voter didn't submit anything themselves.
    assert body["submissions"] == []


async def test_export_includes_club_membership(client, db_session):
    organizer = await _seed_user(db_session, "org3@example.com", name="Org3")
    club = await _seed_club(db_session, organizer.id, name="Fall Mix")

    resp = await client.get(EXPORT_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    memberships = resp.json()["club_memberships"]
    assert len(memberships) == 1
    assert memberships[0]["club_id"] == str(club.id)
    assert memberships[0]["club_name"] == "Fall Mix"
    assert memberships[0]["role"] == "member"


async def test_export_never_includes_another_users_data(client, db_session):
    organizer = await _seed_user(db_session, "org4@example.com", name="Org4")
    stranger = await _seed_user(db_session, "stranger@example.com", name="Stranger")
    club = await _seed_club(db_session, organizer.id)
    mix_ = await _seed_mix(db_session, club.id)
    await _seed_submission(db_session, mix_.id, organizer.id)

    resp = await client.get(EXPORT_URL, headers=_auth_header(stranger.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submissions"] == []
    assert body["club_memberships"] == []
    assert body["profile"]["email"] == "stranger@example.com"
