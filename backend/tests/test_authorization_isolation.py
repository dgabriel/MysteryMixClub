"""MYS-48: cross-tenant / confused-deputy authorization isolation.

The authorization audit confirmed every club-scoped endpoint derives the
club from the *resource* and gates on membership via
``_load_club_as_member`` / ``_load_club_as_organizer``. Per-endpoint suites
already cover the bare non-member (a user who belongs to NO club) -> 403 case.

This file adds the stronger confused-deputy case in one place: an "intruder"
who is a genuine, ACTIVE member of a *different* club B is still denied access
to club A's resources. That proves membership is checked against the
resource's actual club, not merely "is the caller a member of something."

Every club-scoped endpoint is exercised against club A's resources with the
intruder's token; each must return 403. Membership is the first gate, so 403
wins over any state (409) or validation (422) error even when the mix state or
request body would otherwise be wrong. A single positive control proves a real
club A member still gets 200, so the denials fail for the right reason.

PKs are captured into locals before the test reads them post-build; the seed
helpers commit+refresh so no expired-attribute reads occur (see the project's
MissingGreenlet gotcha).
"""

import uuid
from dataclasses import dataclass

import pytest

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
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


async def _seed_club(
    db_session, organizer: User, *, name: str = "L", state: str
) -> tuple[Mix, Submission]:
    """Seed a club (organizer = active member) with one mix + one submission.

    ``state`` is the mix state. The submission is by the organizer so notes /
    submission-scoped endpoints have a real resource to target.
    """
    club = Club(name=name, organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    mix_ = Mix(
        club_id=club.id,
        mix_number=1,
        theme="late summer feels",
        state=state,
        votes_per_player=3,
    )
    db_session.add(mix_)
    await db_session.flush()
    sub = Submission(
        mix_id=mix_.id,
        user_id=organizer.id,
        isrc="USABC1234567",
        title="song",
        artist="Artist",
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(mix_)
    await db_session.refresh(sub)
    return mix_, sub


async def _add_member(db_session, club_id: uuid.UUID, user: User) -> None:
    db_session.add(ClubMember(club_id=club_id, user_id=user.id))
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
    club_a_id: uuid.UUID
    mix_a_id: uuid.UUID
    submission_a_id: uuid.UUID


async def _build(db_session, *, mix_a_state: str) -> _Scenario:
    """Club A (organizer + a second genuine member) plus an intruder who is an
    ACTIVE member of a *separate* club B and is NOT a member of club A."""
    organizer_a = await _seed_user(db_session, "org-a@example.com", "OrgA")
    member_a = await _seed_user(db_session, "member-a@example.com", "MemberA")
    mix_a, sub_a = await _seed_club(db_session, organizer_a, name="Club A", state=mix_a_state)
    await _add_member(db_session, mix_a.club_id, member_a)

    # Club B with the intruder as a real active member — the crux of the test.
    organizer_b = await _seed_user(db_session, "org-b@example.com", "OrgB")
    mix_b, _ = await _seed_club(db_session, organizer_b, name="Club B", state="open_voting")
    intruder = await _seed_user(db_session, "intruder@example.com", "Intruder")
    await _add_member(db_session, mix_b.club_id, intruder)

    return _Scenario(
        organizer_a_id=organizer_a.id,
        member_a_id=member_a.id,
        intruder_id=intruder.id,
        club_a_id=mix_a.club_id,
        mix_a_id=mix_a.id,
        submission_a_id=sub_a.id,
    )


def _assert_blocked(resp, *, organizer_gated: bool = False) -> None:
    """403 must win over any 409/422 state/validation gate.

    Member-gated routes deny with the "you are not a member of this club"
    detail. Organizer-gated routes (``_load_club_as_organizer``) gate purely on
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
# Club-scoped endpoints
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_get_club_detail(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/clubs/{s.club_a_id}", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_list_club_members(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/clubs/{s.club_a_id}/members", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_patch_club(client, db_session):
    # Organizer-gated; the intruder is not even a member of A.
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.patch(
        f"/api/v1/clubs/{s.club_a_id}",
        json={"name": "Hijacked"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_create_invite(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.post(f"/api/v1/clubs/{s.club_a_id}/invites", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_create_mix(client, db_session):
    # Organizer-gated.
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/clubs/{s.club_a_id}/mixes",
        json={"theme": "hijack theme"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_list_mixes(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/clubs/{s.club_a_id}/mixes", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Mix-scoped endpoints (club derived via the mix)
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_get_mix_detail(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/mixes/{s.mix_a_id}", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_patch_mix(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.patch(
        f"/api/v1/mixes/{s.mix_a_id}",
        json={"theme": "hijacked"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp, organizer_gated=True)


async def test_intruder_cannot_get_playlist(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/mixes/{s.mix_a_id}/playlist", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_get_results(client, db_session):
    # Results require a closed mix; membership is still checked first.
    s = await _build(db_session, mix_a_state="closed")
    resp = await client.get(f"/api/v1/mixes/{s.mix_a_id}/results", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_submit(client, db_session):
    s = await _build(db_session, mix_a_state="open_submission")
    resp = await client.post(
        f"/api/v1/mixes/{s.mix_a_id}/submissions",
        json={"isrc": "USABC1234567", "title": "intrusion", "artist": "X"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_own_submission(client, db_session):
    s = await _build(db_session, mix_a_state="open_submission")
    resp = await client.get(
        f"/api/v1/mixes/{s.mix_a_id}/submissions/mine", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


async def test_intruder_cannot_list_submissions(client, db_session):
    # Submission list reveals after close; membership is checked first.
    s = await _build(db_session, mix_a_state="closed")
    resp = await client.get(f"/api/v1/mixes/{s.mix_a_id}/submissions", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


async def test_intruder_cannot_cast_votes(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/mixes/{s.mix_a_id}/votes",
        json={"submission_ids": [str(s.submission_a_id)]},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_own_votes(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(f"/api/v1/mixes/{s.mix_a_id}/votes/mine", headers=_auth(s.intruder_id))
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Submission-scoped endpoints (club derived via submission -> mix)
# --------------------------------------------------------------------------- #


async def test_intruder_cannot_post_note(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.post(
        f"/api/v1/submissions/{s.submission_a_id}/notes",
        json={"body": "intruding"},
        headers=_auth(s.intruder_id),
    )
    _assert_blocked(resp)


async def test_intruder_cannot_get_notes(client, db_session):
    s = await _build(db_session, mix_a_state="open_voting")
    resp = await client.get(
        f"/api/v1/submissions/{s.submission_a_id}/notes", headers=_auth(s.intruder_id)
    )
    _assert_blocked(resp)


# --------------------------------------------------------------------------- #
# Positive control — a genuine member of A still gets through.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("actor", ["organizer", "member"])
async def test_genuine_club_a_member_can_read_club(client, db_session, actor):
    s = await _build(db_session, mix_a_state="open_voting")
    actor_id = s.organizer_a_id if actor == "organizer" else s.member_a_id
    resp = await client.get(f"/api/v1/clubs/{s.club_a_id}", headers=_auth(actor_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(s.club_a_id)
