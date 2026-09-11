"""Tests for MysteryMixClub-ps1w.1: GET /users/me/submissions.

The caller's own cross-club submission history. Vote identity and other
players' notes must follow the same visibility rules as the closed-mix reveal
(MYS-173) and GET /submissions/:id/notes (MYS-67) -- this endpoint doesn't
introduce a new leak just because it's scoped to "my" data.
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

HISTORY_URL = "/api/v1/users/me/submissions"


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer_id, *, name="Club") -> Club:
    club = Club(name=name, organizer_id=organizer_id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer_id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_mix(
    db_session, club_id, *, number=1, state="open_submission", theme="a theme"
) -> Mix:
    mix_ = Mix(club_id=club_id, mix_number=number, theme=theme, state=state, votes_per_player=3)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _seed_submission(
    db_session, mix_id, user_id, *, isrc="USABC1234567", source_key=None, note=None
) -> Submission:
    sub = Submission(
        mix_id=mix_id,
        user_id=user_id,
        isrc=isrc,
        source_key=source_key,
        title="song",
        artist="Artist",
        note=note,
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, mix_id, voter_id, submission_id, *, weight=1) -> Vote:
    vote = Vote(mix_id=mix_id, voter_id=voter_id, submission_id=submission_id, weight=weight)
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


async def test_history_requires_auth(client, db_session):
    resp = await client.get(HISTORY_URL)
    assert resp.status_code == 401


async def test_history_empty_for_a_user_with_no_submissions(client, db_session):
    user = await _seed_user(db_session, "empty@example.com")

    resp = await client.get(HISTORY_URL, headers=_auth_header(user.id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_history_includes_club_and_mix_context(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com", name="Org")
    club = await _seed_club(db_session, organizer.id, name="Fall Mix")
    mix_ = await _seed_mix(db_session, club.id, number=2, theme="road trip")
    submission = await _seed_submission(db_session, mix_.id, organizer.id, note="context")

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["submission_id"] == str(submission.id)
    assert entry["club_id"] == str(club.id)
    assert entry["club_name"] == "Fall Mix"
    assert entry["mix_id"] == str(mix_.id)
    assert entry["mix_number"] == 2
    assert entry["theme"] == "road trip"
    assert entry["state"] == "open_submission"
    assert entry["title"] == "song"
    assert entry["submitter_note"] == "context"


async def test_history_includes_source_only_submission(client, db_session):
    organizer = await _seed_user(db_session, "src@example.com", name="Src")
    club = await _seed_club(db_session, organizer.id)
    mix_ = await _seed_mix(db_session, club.id)
    await _seed_submission(
        db_session, mix_.id, organizer.id, isrc=None, source_key="youtube:PRpiBpDy7MQ"
    )

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["isrc"] is None
    assert entry["source"] == "youtube"
    assert entry["source_url"] is not None


async def test_history_hides_vote_identity_and_count_while_mix_is_open(client, db_session):
    organizer = await _seed_user(db_session, "org2@example.com", name="Org2")
    voter = await _seed_user(db_session, "voter@example.com", name="Voter")
    club = await _seed_club(db_session, organizer.id)
    db_session.add(ClubMember(club_id=club.id, user_id=voter.id))
    await db_session.commit()
    mix_ = await _seed_mix(db_session, club.id, state="open_voting")
    submission = await _seed_submission(db_session, mix_.id, organizer.id)
    await _seed_vote(db_session, mix_.id, voter.id, submission.id)

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    # Hidden, not zero -- an open mix's real vote count is not the same as
    # "revealed to be zero" (MYS-173 anonymity holds even for your own song).
    assert entry["vote_count"] is None
    assert entry["voters"] == []


async def test_history_reveals_vote_identity_once_mix_closes(client, db_session):
    organizer = await _seed_user(db_session, "org3@example.com", name="Org3")
    voter = await _seed_user(db_session, "voter2@example.com", name="Voter2")
    club = await _seed_club(db_session, organizer.id)
    db_session.add(ClubMember(club_id=club.id, user_id=voter.id))
    await db_session.commit()
    mix_ = await _seed_mix(db_session, club.id, state="closed")
    submission = await _seed_submission(db_session, mix_.id, organizer.id)
    await _seed_vote(db_session, mix_.id, voter.id, submission.id, weight=2)

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert entry["vote_count"] == 2
    assert len(entry["voters"]) == 1
    assert entry["voters"][0]["display_name"] == "Voter2"
    assert entry["voters"][0]["weight"] == 2


async def test_history_hides_others_notes_while_mix_is_open(client, db_session):
    organizer = await _seed_user(db_session, "org4@example.com", name="Org4")
    other = await _seed_user(db_session, "other@example.com", name="Other")
    club = await _seed_club(db_session, organizer.id)
    db_session.add(ClubMember(club_id=club.id, user_id=other.id))
    await db_session.commit()
    mix_ = await _seed_mix(db_session, club.id, state="open_voting")
    submission = await _seed_submission(db_session, mix_.id, organizer.id)
    await _seed_note(db_session, mix_.id, other.id, submission.id, body="secret take")

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    # The submitter viewing their OWN song still can't see another member's
    # note before the mix closes -- same anti-collusion rule as MYS-67.
    assert entry["notes"] == []


async def test_history_reveals_all_notes_once_mix_closes(client, db_session):
    organizer = await _seed_user(db_session, "org5@example.com", name="Org5")
    other = await _seed_user(db_session, "other2@example.com", name="Other2")
    club = await _seed_club(db_session, organizer.id)
    db_session.add(ClubMember(club_id=club.id, user_id=other.id))
    await db_session.commit()
    mix_ = await _seed_mix(db_session, club.id, state="closed")
    submission = await _seed_submission(db_session, mix_.id, organizer.id)
    await _seed_note(db_session, mix_.id, other.id, submission.id, body="great pick")

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    entry = resp.json()[0]
    assert len(entry["notes"]) == 1
    assert entry["notes"][0]["body"] == "great pick"
    assert entry["notes"][0]["author_display_name"] == "Other2"


async def test_history_never_includes_another_users_submissions(client, db_session):
    organizer = await _seed_user(db_session, "org6@example.com", name="Org6")
    stranger = await _seed_user(db_session, "stranger@example.com", name="Stranger")
    club = await _seed_club(db_session, organizer.id)
    mix_ = await _seed_mix(db_session, club.id)
    await _seed_submission(db_session, mix_.id, organizer.id)

    resp = await client.get(HISTORY_URL, headers=_auth_header(stranger.id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_history_orders_newest_submission_first(client, db_session):
    organizer = await _seed_user(db_session, "org7@example.com", name="Org7")
    club = await _seed_club(db_session, organizer.id)
    mix_1 = await _seed_mix(db_session, club.id, number=1)
    mix_2 = await _seed_mix(db_session, club.id, number=2)
    first = await _seed_submission(db_session, mix_1.id, organizer.id)
    second = await _seed_submission(db_session, mix_2.id, organizer.id, isrc="USXYZ7654321")
    # Two submissions created back-to-back can otherwise land in the same
    # timestamp instant, making DESC order ambiguous -- force a real gap.
    now = datetime.now(timezone.utc)
    first.created_at = now - timedelta(minutes=1)
    second.created_at = now
    await db_session.commit()

    resp = await client.get(HISTORY_URL, headers=_auth_header(organizer.id))

    assert resp.status_code == 200, resp.text
    ids = [e["submission_id"] for e in resp.json()]
    assert ids == [str(second.id), str(first.id)]
