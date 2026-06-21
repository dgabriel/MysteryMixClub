"""Tests for MYS-21: notes endpoints.

Covers the auth/membership/404 gates, the POST-only ``open_voting`` round-state
gate, and Pydantic body validation (1..280 chars, whitespace stripped). Also
asserts the product rules: self-notes are allowed, vibing submissions are
eligible, GET is gated by round state (during voting a member sees only their
own notes; the full set is revealed once closed — MYS-67), GET returns [] when
empty, multiple notes by the same author persist, GET is ordered by created_at
asc, and author_display_name is joined correctly.
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name, default_vibe_mode=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league_with_round(
    db_session, organizer: User, *, state: str = "open_voting"
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


async def _seed_submission(
    db_session, round_: Round, user: User, *, title: str = "bad guy", mode: str = "playing"
) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title=title,
        artist="Billie Eilish",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(submission_id) -> str:
    return f"/api/v1/submissions/{submission_id}/notes"


# --------------------------------------------------------------------------- #
# POST — gates
# --------------------------------------------------------------------------- #


async def test_post_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "love this"})
    assert resp.status_code == 401


async def test_post_unknown_submission_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    resp = await client.post(
        _url(uuid.uuid4()), json={"body": "love this"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "submission not found"


async def test_post_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "love this"}, headers=_auth(outsider.id))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "you are not a member of this league"


async def test_post_when_not_open_voting_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_submission")
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "love this"}, headers=_auth(organizer.id))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "notes can be left while voting is open"


async def test_post_when_closed_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="closed")
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "too late"}, headers=_auth(organizer.id))
    assert resp.status_code == 409


async def test_post_empty_body_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": ""}, headers=_auth(organizer.id))
    assert resp.status_code == 422


async def test_post_whitespace_only_body_422(client, db_session):
    # strip_whitespace=True + min_length=1 means whitespace-only collapses to empty.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "    "}, headers=_auth(organizer.id))
    assert resp.status_code == 422


async def test_post_body_too_long_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "x" * 281}, headers=_auth(organizer.id))
    assert resp.status_code == 422


async def test_post_missing_body_422(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={}, headers=_auth(organizer.id))
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# POST — happy paths + product rules
# --------------------------------------------------------------------------- #


async def test_post_self_note_allowed(client, db_session):
    # A player may leave a note on their OWN submission.
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id, round_id = sub.id, round_.id
    resp = await client.post(
        _url(sub_id), json={"body": "  shameless self-love  "}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["submission_id"] == str(sub_id)
    assert body["round_id"] == str(round_id)
    assert body["author_id"] == str(organizer.id)
    assert body["author_display_name"] == "Org"
    assert body["body"] == "shameless self-love"  # stripped
    assert body["created_at"] is not None
    assert uuid.UUID(body["id"])


async def test_post_note_on_other_members_submission(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    member = await _seed_user(db_session, "m@example.com", name="Mara")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.post(_url(sub.id), json={"body": "banger"}, headers=_auth(member.id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["author_display_name"] == "Mara"


async def test_post_note_on_vibing_submission_allowed(client, db_session):
    # Eligibility is participation-mode-agnostic.
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    sub = await _seed_submission(db_session, round_, member, mode="vibing")
    resp = await client.post(_url(sub.id), json={"body": "vibes only"}, headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text


async def test_post_multiple_notes_same_author_allowed(client, db_session):
    # No unique constraint: multiple notes per author per submission persist.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id = sub.id
    r1 = await client.post(
        _url(sub_id), json={"body": "first thought"}, headers=_auth(organizer.id)
    )
    r2 = await client.post(
        _url(sub_id), json={"body": "second thought"}, headers=_auth(organizer.id)
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    db_session.expire_all()
    rows = (await db_session.scalars(select(Note).where(Note.submission_id == sub_id))).all()
    assert len(rows) == 2
    assert {n.body for n in rows} == {"first thought", "second thought"}


# --------------------------------------------------------------------------- #
# GET — gates
# --------------------------------------------------------------------------- #


async def test_get_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.get(_url(sub.id))
    assert resp.status_code == 401


async def test_get_unknown_submission_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    resp = await client.get(_url(uuid.uuid4()), headers=_auth(organizer.id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "submission not found"


async def test_get_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.get(_url(sub.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# GET — happy paths + product rules
# --------------------------------------------------------------------------- #


async def test_get_empty_returns_empty_list(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer)
    resp = await client.get(_url(sub.id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_get_returns_notes_ordered_by_created_at_asc(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    member = await _seed_user(db_session, "m@example.com", name="Mara")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    await _add_member(db_session, round_.league_id, member)
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id = sub.id
    # POST three notes in order; created_at is server-assigned per insert.
    await client.post(_url(sub_id), json={"body": "one"}, headers=_auth(organizer.id))
    await client.post(_url(sub_id), json={"body": "two"}, headers=_auth(member.id))
    await client.post(_url(sub_id), json={"body": "three"}, headers=_auth(organizer.id))

    # Close the round so the full multi-author set is visible (during voting a
    # member would only see their own — see test_get_hides_others_notes...).
    db_round = await db_session.scalar(select(Round).where(Round.id == round_id))
    db_round.state = "closed"
    await db_session.commit()

    resp = await client.get(_url(sub_id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    notes = resp.json()
    assert [n["body"] for n in notes] == ["one", "two", "three"]
    # author_display_name joined correctly to the author of each note.
    assert [n["author_display_name"] for n in notes] == ["Org", "Mara", "Org"]


async def test_get_hides_others_notes_during_voting(client, db_session):
    # MYS-67: while voting is open, a member sees only their own notes — others'
    # stay hidden so they can't sway votes. The reveal (close) lifts this.
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    member = await _seed_user(db_session, "m@example.com", name="Mara")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    round_id = round_.id
    await _add_member(db_session, round_.league_id, member)
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id = sub.id
    await client.post(
        _url(sub_id), json={"body": "from the organizer"}, headers=_auth(organizer.id)
    )
    await client.post(_url(sub_id), json={"body": "from me"}, headers=_auth(member.id))

    # During voting, the member sees only their own note.
    resp = await client.get(_url(sub_id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    assert [n["body"] for n in resp.json()] == ["from me"]

    # Once closed, the full set is revealed.
    db_round = await db_session.scalar(select(Round).where(Round.id == round_id))
    db_round.state = "closed"
    await db_session.commit()
    resp = await client.get(_url(sub_id), headers=_auth(member.id))
    assert {n["body"] for n in resp.json()} == {"from the organizer", "from me"}


async def test_get_works_when_round_closed(client, db_session):
    # Notes remain readable (in full) after close — the reveal.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    sub = await _seed_submission(db_session, round_, organizer)
    sub_id, round_id = sub.id, round_.id
    await client.post(_url(sub_id), json={"body": "frozen in time"}, headers=_auth(organizer.id))

    db_round = await db_session.scalar(select(Round).where(Round.id == round_id))
    db_round.state = "closed"
    await db_session.commit()

    resp = await client.get(_url(sub_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert [n["body"] for n in resp.json()] == ["frozen in time"]


async def test_get_only_returns_notes_for_that_submission(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, member)
    sub_a = await _seed_submission(db_session, round_, organizer, title="A")
    sub_b = await _seed_submission(db_session, round_, member, title="B")
    sub_a_id, sub_b_id = sub_a.id, sub_b.id

    await client.post(_url(sub_a_id), json={"body": "for A"}, headers=_auth(organizer.id))
    await client.post(_url(sub_b_id), json={"body": "for B"}, headers=_auth(organizer.id))

    resp = await client.get(_url(sub_a_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    bodies = [n["body"] for n in resp.json()]
    assert bodies == ["for A"]
