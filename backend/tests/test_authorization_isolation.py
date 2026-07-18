"""MYS-48: cross-tenant / confused-deputy authorization isolation.

The authorization audit confirmed every league-scoped endpoint derives the
league from the *resource* and gates on membership via
``_load_league_as_member`` / ``_load_league_as_organizer``. Per-endpoint suites
already cover the bare non-member (a user who belongs to NO league) -> 403 case.

This file adds the stronger confused-deputy case in one place: an "intruder"
who is a genuine, ACTIVE member of a *different* league B is still denied access
to league A's resources. That proves membership is checked against the
resource's actual league, not merely "is the caller a member of something."

Every league-scoped endpoint is exercised against league A's resources with the
intruder's token; each must return 403. Membership is the first gate, so 403
wins over any state (409) or validation (422) error even when the round state or
request body would otherwise be wrong. A single positive control proves a real
league A member still gets 200, so the denials fail for the right reason.

PKs are captured into locals before the test reads them post-build; the seed
helpers commit+refresh so no expired-attribute reads occur (see the project's
MissingGreenlet gotcha).
"""

import uuid
from dataclasses import dataclass

import pytest

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User


# --------------------------------------------------------------------------- #
# Seeding helpers (mirrors the per-endpoint suites' factories)
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(
    db_session, organizer: User, *, name: str = "L", state: str
) -> tuple[Round, Submission]:
    """Seed a league (organizer = active member) with one round + one submission.

    ``state`` is the round state. The submission is by the organizer so notes /
    submission-scoped endpoints have a real resource to target.
    """
    league = League(name=name, organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="late summer feels",
        state=state,
        votes_per_player=3,
    )
    db_session.add(round_)
    await db_session.flush()
    sub = Submission(
        round_id=round_.id,
        user_id=organizer.id,
        isrc="USABC1234567",
        title="song",
        artist="Artist",
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(round_)
    await db_session.refresh(sub)
    return round_, sub


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# --------------------------------------------------------------------------- #
# Scenario builder
# --------------------------------------------------------------------------- #


@dataclass
class _Scenario:
    organizer_a_id: uuid.UUID
    member_a_id: uuid.UUID
    intruder_id: uuid.UUID
    league_a_id: uuid.UUID
    round_a_id: uuid.UUID
    submission_a_id: uuid.UUID


async def _build(db_session, *, round_a_state: str) -> _Scenario:
    """League A (organizer + a second genuine member) plus an intruder who is an
    ACTIVE member of a *separate* league B and is NOT a member of league A."""
    organizer_a = await _seed_user(db_session, "org-a@example.com", "OrgA")
    member_a = await _seed_user(db_session, "member-a@example.com", "MemberA")
    round_a, sub_a = await _seed_league(
        db_session, organizer_a, name="League A", state=round_a_state
    )
    await _add_member(db_session, round_a.league_id, member_a)

    # League B with the intruder as a real active member — the crux of the test.
    organizer_b = await _seed_user(db_session, "org-b@example.com", "OrgB")
    round_b, _ = await _seed_league(db_session, organizer_b, name="League B", state="open_voting")
    intruder = await _seed_user(db_session, "intruder@example.com", "Intruder")
    await _add_member(db_session, round_b.league_id, intruder)

    return _Scenario(
        organizer_a_id=organizer_a.id,
        member_a_id=member_a.id,
        intruder_id=intruder.id,
        league_a_id=round_a.league_id,
        round_a_id=round_a.id,
        submission_a_id=sub_a.id,
    )


def _assert_blocked(resp, *, organizer_gated: bool = False) -> None:
    """403 must win over any 409/422 state/validation gate.

    Member-gated routes deny with the "you are not a member of this club"
    detail. Organizer-gated routes (``_load_league_as_organizer``) gate purely on
    organizer identity and deny a non-member with an organizer-phrased detail
    ("only the organizer can ..."); the status is still the load-bearing 403, so
    both phrasings are accepted there.
    """
    assert resp.status_code == 403, resp.text
    detail = resp.json().get("detail", "").lower()
    if organizer_gated:
        assert "member" in detail or "organizer" in detail, detail
    else:
        assert "member" in detail, detail


# --------------------------------------------------------------------------- #
# League-scoped endpoints
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_get_league_detail(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(f"/api/v1/leagues/{s.league_a_id}", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_list_league_members(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(
        f"/api/v1/leagues/{s.league_a_id}/members", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


async def test_intruder_cannot_patch_league(client, db_session):
    # Organizer-gated; the intruder is not even a member of A.
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.patch(
        f"/api/v1/leagues/{s.league_a_id}",
        json={"name": "Hijacked"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_create_invite(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/leagues/{s.league_a_id}/invites", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


async def test_intruder_cannot_create_round(client, db_session):
    # Organizer-gated.
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/leagues/{s.league_a_id}/rounds",
        json={"theme": "hijack theme"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_list_rounds(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(f"/api/v1/leagues/{s.league_a_id}/rounds", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Round-scoped endpoints (league derived via the round)
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_get_round_detail(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(f"/api/v1/rounds/{s.round_a_id}", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_patch_round(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.patch(
        f"/api/v1/rounds/{s.round_a_id}",
        json={"theme": "hijacked"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_get_playlist(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(f"/api/v1/rounds/{s.round_a_id}/playlist", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_get_results(client, db_session):
    # Results require a closed round; membership is still checked first.
    s = await _build(db_session, round_a_state="closed")
    resp = await client.get(f"/api/v1/rounds/{s.round_a_id}/results", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_submit(client, db_session):
    s = await _build(db_session, round_a_state="open_submission")
    resp = await client.post(
        f"/api/v1/rounds/{s.round_a_id}/submissions",
        json={"isrc": "USABC1234567", "title": "intrusion", "artist": "X"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_own_submission(client, db_session):
    s = await _build(db_session, round_a_state="open_submission")
    resp = await client.get(
        f"/api/v1/rounds/{s.round_a_id}/submissions/mine", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


async def test_intruder_cannot_list_submissions(client, db_session):
    # Submission list reveals after close; membership is checked first.
    s = await _build(db_session, round_a_state="closed")
    resp = await client.get(
        f"/api/v1/rounds/{s.round_a_id}/submissions", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


async def test_intruder_cannot_cast_votes(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/rounds/{s.round_a_id}/votes",
        json={"submission_ids": [str(s.submission_a_id)]},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_own_votes(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(
        f"/api/v1/rounds/{s.round_a_id}/votes/mine", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Submission-scoped endpoints (league derived via submission -> round)
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_post_note(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/submissions/{s.submission_a_id}/notes",
        json={"body": "intruding"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_notes(client, db_session):
    s = await _build(db_session, round_a_state="open_voting")
    resp = await client.get(
        f"/api/v1/submissions/{s.submission_a_id}/notes", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Positive control — a genuine member of A still gets through.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("actor", ["organizer", "member"])
async def test_genuine_league_a_member_can_read_league(client, db_session, actor):
    s = await _build(db_session, round_a_state="open_voting")
    actor_id = s.organizer_a_id if actor == "organizer" else s.member_a_id
    resp = await client.get(f"/api/v1/leagues/{s.league_a_id}", headers=_auth(actor_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(s.league_a_id)
