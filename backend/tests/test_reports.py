"""Tests for MysteryMixClub-4vii.13: the reports endpoint.

Covers the auth/membership/404 gates, the self-report block, and that a
successful report persists with the reported note's real author (not
whatever the caller claims) and defaults to status "open".
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.report import Report
from app.models.submission import Submission
from app.models.user import User


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club_with_mix(db_session, organizer: User, *, state: str = "closed") -> Mix:
    club = Club(name="L", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    mix_ = Mix(club_id=club.id, mix_number=1, theme="late summer", state=state)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _add_member(db_session, club_id: uuid.UUID, user: User) -> None:
    db_session.add(ClubMember(club_id=club_id, user_id=user.id))
    await db_session.commit()


async def _seed_note(db_session, mix_: Mix, author: User, *, body: str = "meh, skip") -> Note:
    # Note.submission_id carries a real FK -- needs an actual Submission row,
    # even though the reports endpoint itself never reads it.
    sub = Submission(
        mix_id=mix_.id,
        user_id=author.id,
        isrc="USABC1234567",
        title="bad guy",
        artist="Billie Eilish",
    )
    db_session.add(sub)
    await db_session.flush()
    note = Note(mix_id=mix_.id, author_id=author.id, submission_id=sub.id, body=body)
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)
    return note


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def test_post_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_club_with_mix(db_session, organizer)
    note = await _seed_note(db_session, mix_, organizer)
    resp = await client.post(
        "/api/v1/reports",
        json={"content_type": "note", "content_id": str(note.id), "reason": "spam"},
    )
    assert resp.status_code == 401


async def test_post_unknown_note_404(client, db_session):
    reporter = await _seed_user(db_session, "r@example.com")
    resp = await client.post(
        "/api/v1/reports",
        json={"content_type": "note", "content_id": str(uuid.uuid4()), "reason": "spam"},
        headers=_auth(reporter.id),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "content not found"


async def test_post_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    mix_ = await _seed_club_with_mix(db_session, organizer)
    note = await _seed_note(db_session, mix_, organizer)
    resp = await client.post(
        "/api/v1/reports",
        json={"content_type": "note", "content_id": str(note.id), "reason": "spam"},
        headers=_auth(outsider.id),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "you are not a member of this club"


async def test_post_own_note_400(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_club_with_mix(db_session, organizer)
    note = await _seed_note(db_session, mix_, organizer)
    resp = await client.post(
        "/api/v1/reports",
        json={"content_type": "note", "content_id": str(note.id), "reason": "spam"},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "you can't report your own content"


async def test_post_success_persists_real_author_and_defaults_open(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    reporter = await _seed_user(db_session, "r@example.com")
    mix_ = await _seed_club_with_mix(db_session, organizer)
    await _add_member(db_session, mix_.club_id, reporter)
    note = await _seed_note(db_session, mix_, organizer, body="this is spam")

    resp = await client.post(
        "/api/v1/reports",
        json={
            "content_type": "note",
            "content_id": str(note.id),
            "reason": "spam",
            "detail": "posted the same link everywhere",
        },
        headers=_auth(reporter.id),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "open"

    report = await db_session.scalar(select(Report).where(Report.id == uuid.UUID(body["id"])))
    assert report is not None
    assert report.reporter_id == reporter.id
    # Reported user comes from the note's real author, not anything the
    # caller could have supplied themselves.
    assert report.reported_user_id == organizer.id
    assert report.club_id == mix_.club_id
    assert report.reason == "spam"
    assert report.detail == "posted the same link everywhere"


async def test_post_rejects_bad_reason(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    reporter = await _seed_user(db_session, "r@example.com")
    mix_ = await _seed_club_with_mix(db_session, organizer)
    await _add_member(db_session, mix_.club_id, reporter)
    note = await _seed_note(db_session, mix_, organizer)

    resp = await client.post(
        "/api/v1/reports",
        json={"content_type": "note", "content_id": str(note.id), "reason": "not-a-real-reason"},
        headers=_auth(reporter.id),
    )
    assert resp.status_code == 422
