"""Tests for MYS-124: DELETE /api/v1/clubs/{club_id} (organizer-only, cascade).

A club can be hard-deleted by its organizer in ANY state (MYS-137) — not
started, in progress (a mix open), or complete. The delete cascades, in FK
dependency order, to votes, notes, submissions, mixes, invites, and
club_members — leaving no orphan rows. The users themselves are NOT deleted.

Covers: 401 unauthenticated, 403 non-organizer, 404 missing club, and 204 +
no-orphans for a not-started club, an in-flight club (open mix with
submission/vote), and a complete club with real mix data.

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha). See technical-design.md §6 and the MYS-124 plan.
"""

import uuid

from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.note import Note
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, **overrides) -> User:
    defaults = {
        "email": "alice@example.com",
        "display_name": "Alice",
        "preferred_service": None,
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer: User, **overrides) -> Club:
    defaults = {
        "name": "Summer Bangers",
        "description": "A club for hot tracks",
        "organizer_id": organizer.id,
        "total_mixes": 6,
        "votes_per_player": 5,
        "current_mix": 0,
        "state": "active",
    }
    defaults.update(overrides)
    club = Club(**defaults)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_member(db_session, club: Club, user: User, **overrides) -> ClubMember:
    defaults = {"club_id": club.id, "user_id": user.id}
    defaults.update(overrides)
    member = ClubMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _delete_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}"


async def _count(db_session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


# ========================================================================== #
# Auth / not found
# ========================================================================== #


async def test_delete_unauthenticated_returns_401(client, db_session):
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer)

    resp = await client.delete(_delete_url(club.id))

    assert resp.status_code == 401, resp.text


async def test_delete_missing_club_returns_404(client, db_session):
    user = await _seed_user(db_session)

    resp = await client.delete(_delete_url(uuid.uuid4()), headers=_auth_header(user.id))

    assert resp.status_code == 404, resp.text


async def test_delete_non_organizer_member_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(member.id))

    assert resp.status_code == 403, resp.text

    # The club still exists.
    club_id = club.id
    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == club_id)) is not None


async def test_delete_outsider_returns_403(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    outsider = await _seed_user(db_session, email="out@example.com", display_name="Out")

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(outsider.id))

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# In-flight club — now deletable in any state (MYS-137)
# ========================================================================== #


async def test_delete_in_flight_club_is_allowed_and_cascades(client, db_session):
    # MYS-137: an in-progress club (state == active AND current_mix > 0, with
    # an open mix + submission + vote) can be deleted, and everything cascades.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, state="active", current_mix=1)
    player = await _seed_user(db_session, email="player@example.com", display_name="Player")
    await _seed_member(db_session, club, player)

    mix_ = Mix(club_id=club.id, mix_number=1, state="open_voting")
    db_session.add(mix_)
    await db_session.flush()
    submission = Submission(
        mix_id=mix_.id,
        user_id=player.id,
        isrc="USEXAMPLE0009",
        title="Mid-mix Song",
        artist="An Artist",
    )
    db_session.add(submission)
    await db_session.flush()
    db_session.add(Vote(mix_id=mix_.id, voter_id=organizer.id, submission_id=submission.id))
    await db_session.commit()

    club_id = club.id
    mix_id = mix_.id

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == club_id)) is None
    assert await _count(db_session, Mix, club_id=club_id) == 0
    assert await _count(db_session, Submission, mix_id=mix_id) == 0
    assert await _count(db_session, Vote, mix_id=mix_id) == 0


async def test_delete_active_but_not_started_club_is_allowed(client, db_session):
    # state == active but current_mix == 0 -> not yet started, delete is fine.
    organizer = await _seed_user(db_session)
    club = await _seed_club(db_session, organizer, state="active", current_mix=0)

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text


# ========================================================================== #
# Happy path — not-started club, 204 + no orphans
# ========================================================================== #


async def test_delete_not_started_club_cascades_mixes_invites_members(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, current_mix=0)
    member = await _seed_user(db_session, email="member@example.com", display_name="Member")
    await _seed_member(db_session, club, member)
    # A pending mix slate (as auto-generated at creation) + an email invite.
    db_session.add(Mix(club_id=club.id, mix_number=1, state="pending"))
    db_session.add(Mix(club_id=club.id, mix_number=2, state="pending"))
    db_session.add(
        Invite(
            club_id=club.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    club_id = club.id
    organizer_id = organizer.id
    member_id = member.id

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == club_id)) is None
    assert await _count(db_session, Mix, club_id=club_id) == 0
    assert await _count(db_session, Invite, club_id=club_id) == 0
    assert await _count(db_session, ClubMember, club_id=club_id) == 0
    # The user accounts survive the club deletion.
    assert await db_session.scalar(select(User).where(User.id == organizer_id)) is not None
    assert await db_session.scalar(select(User).where(User.id == member_id)) is not None


# ========================================================================== #
# Happy path — complete club with real data, 204 + no orphans
# ========================================================================== #


async def test_delete_complete_club_cascades_submissions_votes_notes(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, state="complete", current_mix=1)
    player = await _seed_user(db_session, email="player@example.com", display_name="Player")
    await _seed_member(db_session, club, player)

    # A closed mix with a submission, a vote, and a note.
    mix_ = Mix(club_id=club.id, mix_number=1, state="closed")
    db_session.add(mix_)
    await db_session.flush()
    submission = Submission(
        mix_id=mix_.id,
        user_id=player.id,
        isrc="USEXAMPLE0001",
        title="A Song",
        artist="An Artist",
    )
    db_session.add(submission)
    await db_session.flush()
    db_session.add(Vote(mix_id=mix_.id, voter_id=organizer.id, submission_id=submission.id))
    db_session.add(
        Note(
            mix_id=mix_.id,
            author_id=organizer.id,
            submission_id=submission.id,
            body="great pick",
        )
    )
    db_session.add(
        Invite(
            club_id=club.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    club_id = club.id
    mix_id = mix_.id
    organizer_id = organizer.id
    player_id = player.id

    resp = await client.delete(_delete_url(club.id), headers=_auth_header(organizer.id))

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    # Nothing tied to this club or its mix survives.
    assert await db_session.scalar(select(Club).where(Club.id == club_id)) is None
    assert await _count(db_session, Mix, club_id=club_id) == 0
    assert await _count(db_session, Submission, mix_id=mix_id) == 0
    assert await _count(db_session, Vote, mix_id=mix_id) == 0
    assert await _count(db_session, Note, mix_id=mix_id) == 0
    assert await _count(db_session, Invite, club_id=club_id) == 0
    assert await _count(db_session, ClubMember, club_id=club_id) == 0
    # Users are untouched.
    assert await db_session.scalar(select(User).where(User.id == organizer_id)) is not None
    assert await db_session.scalar(select(User).where(User.id == player_id)) is not None


async def test_delete_only_targets_its_own_club(client, db_session):
    # A second club's data must be left fully intact.
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    doomed = await _seed_club(db_session, organizer, name="Doomed", current_mix=0)
    keeper = await _seed_club(db_session, organizer, name="Keeper", current_mix=0)
    db_session.add(Mix(club_id=keeper.id, mix_number=1, state="pending"))
    db_session.add(
        Invite(
            club_id=keeper.id,
            created_by=organizer.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    keeper_id = keeper.id

    resp = await client.delete(_delete_url(doomed.id), headers=_auth_header(organizer.id))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == keeper_id)) is not None
    assert await _count(db_session, Mix, club_id=keeper_id) == 1
    assert await _count(db_session, Invite, club_id=keeper_id) == 1
    # Keeper's organizer membership row still present.
    assert await _count(db_session, ClubMember, club_id=keeper_id) == 1
