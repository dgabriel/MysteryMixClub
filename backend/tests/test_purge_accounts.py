"""Tests for MYS-50: purge_deleted_accounts (right-to-be-forgotten hard purge).

DELETE /users/me soft-deletes; this scheduled job finishes the job by
hard-deleting accounts soft-deleted more than ``retention_days`` ago and
cascading to every piece of personal data — notes, votes, submissions, league
memberships, sessions, magic-link tokens at the tombstoned email — and nulling
the organizer FK on any leagues the purged account organized. It returns the
number of accounts purged.

Tests call ``purge_deleted_accounts(db_session, now=...)`` directly with an
explicit ``now`` to drive the 30-day window deterministically. PKs are captured
into locals before any expire_all (project MissingGreenlet gotcha).

Covers: full cascade with zero orphans, the within-retention boundary, the
never-deleted user, organizer-FK nulling that preserves co-members' history, and
the count return value with multiple eligible accounts. See technical-design §10.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.jobs.purge_accounts import purge_deleted_accounts
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.magic_link_token import MagicLinkToken
from app.models.note import Note
from app.models.mix import Mix
from app.models.session import Session
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

# Fixed clock so the retention window is deterministic.
NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, deleted_at=None, name: str = "User") -> User:
    user = User(email=email, display_name=name, deleted_at=deleted_at)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league(db_session, organizer_id, *, name="L", state="active") -> Club:
    league = Club(
        name=name, organizer_id=organizer_id, total_mixes=3, votes_per_player=3, state=state
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=organizer_id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_round(db_session, league_id, *, number=1, state="closed") -> Mix:
    round_ = Mix(
        club_id=league_id,
        mix_number=number,
        theme="a theme",
        state=state,
        votes_per_player=3,
    )
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _seed_submission(db_session, round_id, user_id, *, isrc="USABC1234567") -> Submission:
    sub = Submission(
        mix_id=round_id,
        user_id=user_id,
        isrc=isrc,
        title="song",
        artist="Artist",
        participation_mode="playing",
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, round_id, voter_id, submission_id) -> Vote:
    vote = Vote(mix_id=round_id, voter_id=voter_id, submission_id=submission_id)
    db_session.add(vote)
    await db_session.commit()
    await db_session.refresh(vote)
    return vote


async def _seed_note(db_session, round_id, author_id, submission_id, body="nice") -> Note:
    note = Note(mix_id=round_id, author_id=author_id, submission_id=submission_id, body=body)
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)
    return note


async def _seed_invite(db_session, league_id, created_by) -> Invite:
    invite = Invite(
        club_id=league_id,
        created_by=created_by,
        token="tok-" + uuid.uuid4().hex,
        expires_at=None,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


async def _seed_membership(db_session, league_id, user_id) -> ClubMember:
    member = ClubMember(club_id=league_id, user_id=user_id)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


async def _seed_session(db_session, user_id) -> Session:
    session = Session(user_id=user_id, refresh_token_hash="h-" + uuid.uuid4().hex)
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _seed_magic_token(db_session, email: str) -> MagicLinkToken:
    token = MagicLinkToken(
        email=email,
        token_hash="th-" + uuid.uuid4().hex,
        expires_at=NOW + timedelta(minutes=15),
        used=False,
    )
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)
    return token


async def _count(db_session, model, **filters) -> int:
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


# --------------------------------------------------------------------------- #
# Eligible user fully cascaded — no orphans
# --------------------------------------------------------------------------- #


async def test_eligible_user_fully_cascaded(client, db_session):
    """A user soft-deleted 31 days ago is purged with every child row removed."""
    # Tombstoned email mirrors what DELETE /users/me writes.
    user = await _seed_user(db_session, email="placeholder@example.com")
    user_id = user.id
    tombstone = f"deleted+{user_id}@deleted.invalid"
    user.email = tombstone
    user.deleted_at = NOW - timedelta(days=31)
    await db_session.commit()

    # A second user to own the round/submission this user votes/notes on.
    other = await _seed_user(db_session, email="other@example.com", name="Other")
    other_id = other.id

    league = await _seed_league(db_session, other_id, name="L1", state="complete")
    league_id = league.id
    round_ = await _seed_round(db_session, league_id)
    round_id = round_.id

    # The purged user's own data.
    my_sub = await _seed_submission(db_session, round_id, user_id)
    my_sub_id = my_sub.id
    other_sub = await _seed_submission(db_session, round_id, other_id, isrc="GBXYZ7654321")
    other_sub_id = other_sub.id

    await _seed_vote(db_session, round_id, user_id, other_sub_id)
    await _seed_note(db_session, round_id, user_id, other_sub_id)
    await _seed_membership(db_session, league_id, user_id)
    await _seed_session(db_session, user_id)
    await _seed_magic_token(db_session, tombstone)
    # invites.created_by is a NOT NULL FK to users.id with no ON DELETE — the
    # purge must delete the purged user's invites or the User delete raises
    # IntegrityError (regression guard for the reviewer-found gap).
    await _seed_invite(db_session, league_id, user_id)

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 1

    db_session.expire_all()
    # Zero remaining rows for the purged user across every table.
    assert await _count(db_session, User, id=user_id) == 0
    assert await _count(db_session, Submission, user_id=user_id) == 0
    assert await _count(db_session, Vote, voter_id=user_id) == 0
    assert await _count(db_session, Note, author_id=user_id) == 0
    assert await _count(db_session, ClubMember, user_id=user_id) == 0
    assert await _count(db_session, Session, user_id=user_id) == 0
    assert await _count(db_session, MagicLinkToken, email=tombstone) == 0
    assert await _count(db_session, Invite, created_by=user_id) == 0

    # Sanity: the other user and their submission survive (no over-deletion).
    assert await _count(db_session, User, id=other_id) == 1
    assert await _count(db_session, Submission, id=other_sub_id) == 1
    # The purged user's own submission is gone.
    assert await _count(db_session, Submission, id=my_sub_id) == 0


# --------------------------------------------------------------------------- #
# Invite FK regression: purged user's invites deleted, co-user's invites survive
# --------------------------------------------------------------------------- #


async def test_purged_user_invites_deleted_co_user_invites_survive(client, db_session):
    """Reproduces the reviewer-found blocker: a purged user who created an invite
    is purged without an IntegrityError on the NOT NULL invites.created_by FK.
    A co-user in the same league who created their OWN invite keeps it.

    Without the ``delete(Invite)`` step in the purge, the final User delete would
    raise IntegrityError; with it, the purged user's invite is gone and only the
    co-user's invite survives.
    """
    purged = await _seed_user(db_session, email="purged@example.com", name="Purged")
    purged_id = purged.id
    purged.email = f"deleted+{purged_id}@deleted.invalid"
    purged.deleted_at = NOW - timedelta(days=31)
    await db_session.commit()

    co_user = await _seed_user(db_session, email="co@example.com", name="Co")
    co_user_id = co_user.id

    league = await _seed_league(db_session, co_user_id, name="Shared", state="active")
    league_id = league.id
    await _seed_membership(db_session, league_id, purged_id)

    # The purged user's invite (the one that would trip the FK) and the
    # co-user's own invite in the same league (must survive).
    purged_invite = await _seed_invite(db_session, league_id, purged_id)
    purged_invite_id = purged_invite.id
    co_invite = await _seed_invite(db_session, league_id, co_user_id)
    co_invite_id = co_invite.id

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 1

    db_session.expire_all()
    # The purged user row is gone — no IntegrityError on the invite FK.
    assert await _count(db_session, User, id=purged_id) == 0
    # The purged user's invite is deleted...
    assert await _count(db_session, Invite, id=purged_invite_id) == 0
    assert await _count(db_session, Invite, created_by=purged_id) == 0
    # ...but the co-user and their own invite survive (only the purged user's
    # invites are deleted, not every invite in the league).
    assert await _count(db_session, User, id=co_user_id) == 1
    assert await _count(db_session, Invite, id=co_invite_id) == 1
    assert await _count(db_session, Invite, created_by=co_user_id) == 1


# --------------------------------------------------------------------------- #
# Within retention — not purged
# --------------------------------------------------------------------------- #


async def test_within_retention_not_purged(client, db_session):
    user = await _seed_user(db_session, email="recent@example.com")
    user_id = user.id
    user.email = f"deleted+{user_id}@deleted.invalid"
    user.deleted_at = NOW - timedelta(days=10)
    await db_session.commit()

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 0

    db_session.expire_all()
    assert await _count(db_session, User, id=user_id) == 1


# --------------------------------------------------------------------------- #
# Active (never-deleted) user untouched
# --------------------------------------------------------------------------- #


async def test_not_deleted_user_untouched(client, db_session):
    user = await _seed_user(db_session, email="active@example.com")
    user_id = user.id
    assert user.deleted_at is None

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 0

    db_session.expire_all()
    assert await _count(db_session, User, id=user_id) == 1


# --------------------------------------------------------------------------- #
# Organizer FK nulled; co-member history preserved
# --------------------------------------------------------------------------- #


async def test_purged_organizer_nulls_league_and_preserves_others(client, db_session):
    """A purged user who organized a completed league: the league survives with
    organizer_id IS NULL, a co-member's submission survives, and the purged
    user's own submission is removed."""
    organizer = await _seed_user(db_session, email="org@example.com", name="Org")
    organizer_id = organizer.id
    organizer.email = f"deleted+{organizer_id}@deleted.invalid"
    organizer.deleted_at = NOW - timedelta(days=31)
    await db_session.commit()

    member = await _seed_user(db_session, email="member@example.com", name="Member")
    member_id = member.id

    league = await _seed_league(db_session, organizer_id, name="Completed", state="complete")
    league_id = league.id
    await _seed_membership(db_session, league_id, member_id)
    round_ = await _seed_round(db_session, league_id)
    round_id = round_.id

    org_sub = await _seed_submission(db_session, round_id, organizer_id)
    org_sub_id = org_sub.id
    member_sub = await _seed_submission(db_session, round_id, member_id, isrc="GBXYZ7654321")
    member_sub_id = member_sub.id

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 1

    db_session.expire_all()
    # Club still exists, organizer FK nulled.
    league_row = await db_session.scalar(select(Club).where(Club.id == league_id))
    assert league_row is not None
    assert league_row.organizer_id is None

    # Co-member and their data intact.
    assert await _count(db_session, User, id=member_id) == 1
    assert await _count(db_session, Submission, id=member_sub_id) == 1
    assert await _count(db_session, ClubMember, user_id=member_id) == 1

    # Purged organizer's own submission and account are gone.
    assert await _count(db_session, Submission, id=org_sub_id) == 0
    assert await _count(db_session, User, id=organizer_id) == 0


# --------------------------------------------------------------------------- #
# Count return value with multiple eligible accounts
# --------------------------------------------------------------------------- #


async def test_count_reflects_multiple_eligible(client, db_session):
    eligible_ids = []
    for i in range(3):
        u = await _seed_user(db_session, email=f"e{i}@example.com", name=f"E{i}")
        u.email = f"deleted+{u.id}@deleted.invalid"
        u.deleted_at = NOW - timedelta(days=31 + i)
        await db_session.commit()
        eligible_ids.append(u.id)

    # One within retention and one never-deleted: neither should be purged.
    recent = await _seed_user(db_session, email="recent@example.com")
    recent_id = recent.id
    recent.deleted_at = NOW - timedelta(days=5)
    await db_session.commit()
    active = await _seed_user(db_session, email="active@example.com")
    active_id = active.id

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 3

    db_session.expire_all()
    for uid in eligible_ids:
        assert await _count(db_session, User, id=uid) == 0
    assert await _count(db_session, User, id=recent_id) == 1
    assert await _count(db_session, User, id=active_id) == 1


# --------------------------------------------------------------------------- #
# Boundary: exactly at the retention cutoff is eligible (deleted_at <= cutoff)
# --------------------------------------------------------------------------- #


async def test_exactly_at_cutoff_is_purged(client, db_session):
    """deleted_at == now - retention_days satisfies the <= cutoff comparison."""
    user = await _seed_user(db_session, email="boundary@example.com")
    user_id = user.id
    user.email = f"deleted+{user_id}@deleted.invalid"
    user.deleted_at = NOW - timedelta(days=30)
    await db_session.commit()

    count = await purge_deleted_accounts(db_session, now=NOW)
    assert count == 1

    db_session.expire_all()
    assert await _count(db_session, User, id=user_id) == 0


# --------------------------------------------------------------------------- #
# Module is runnable as a script entrypoint
# --------------------------------------------------------------------------- #


def test_module_has_script_entrypoint():
    """`python -m app.jobs.purge_accounts` is supported: the module exposes the
    async runner it invokes under __main__."""
    import app.jobs.purge_accounts as job

    assert callable(job.purge_deleted_accounts)
    assert callable(job._run)
