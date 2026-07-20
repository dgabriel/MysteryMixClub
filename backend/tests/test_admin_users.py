"""Tests for MYS-128: platform-admin tooling under /api/v1/admin.

A platform admin is any account whose email is in SEED_ADMIN_EMAILS (NOT a login
gate — it only unlocks these tools and is_platform_admin on /users/me).

Covers:
  GET    /admin/users?email=    — substring search over live accounts
  DELETE /admin/users/{id}      — global hard-delete of a bad actor

Authorization (401 unauthenticated, 403 authenticated non-admin), search
matching/limit, hard-delete cascade with zero orphans, the self-delete guard
(409), and the missing-target 404. PKs are captured into locals before any
expire_all (project MissingGreenlet gotcha).
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.note import Note
from app.models.mix import Mix
from app.models.session import Session
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

ADMIN_EMAIL = "admin@example.com"
SEARCH_URL = "/api/v1/admin/users"


def _delete_url(user_id) -> str:
    return f"/api/v1/admin/users/{user_id}"


@pytest.fixture
def seed_admin_emails() -> str:
    """Make ADMIN_EMAIL a platform admin for this module (MYS-128)."""
    return ADMIN_EMAIL


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, *, name: str = "User", deleted_at=None) -> User:
    user = User(email=email, display_name=name, deleted_at=deleted_at)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(db_session) -> User:
    return await _seed_user(db_session, ADMIN_EMAIL, name="Admin")


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _count(db_session, model, **filters) -> int:
    db_session.expire_all()
    stmt = select(func.count()).select_from(model)
    for attr, value in filters.items():
        stmt = stmt.where(getattr(model, attr) == value)
    return await db_session.scalar(stmt)


# ========================================================================== #
# GET /admin/users — authorization
# ========================================================================== #


async def test_search_unauthenticated_returns_401(client, db_session):
    await _seed_admin(db_session)

    resp = await client.get(SEARCH_URL, params={"email": "a"})

    assert resp.status_code == 401, resp.text


async def test_search_non_admin_returns_403(client, db_session):
    # An authenticated but non-admin account is forbidden.
    plain = await _seed_user(db_session, "plain@example.com")

    resp = await client.get(SEARCH_URL, params={"email": "a"}, headers=_auth_header(plain.id))

    assert resp.status_code == 403, resp.text


async def test_search_missing_email_param_returns_422(client, db_session):
    admin = await _seed_admin(db_session)

    resp = await client.get(SEARCH_URL, headers=_auth_header(admin.id))

    assert resp.status_code == 422, resp.text


# ========================================================================== #
# GET /admin/users — matching
# ========================================================================== #


async def test_search_returns_matching_live_accounts_with_shape(client, db_session):
    admin = await _seed_admin(db_session)
    await _seed_user(db_session, "bob@example.com", name="Bob")
    await _seed_user(db_session, "carol@example.com", name="Carol")

    resp = await client.get(SEARCH_URL, params={"email": "bob"}, headers=_auth_header(admin.id))

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert set(data[0].keys()) == {"id", "email", "display_name", "created_at"}
    assert data[0]["email"] == "bob@example.com"
    assert data[0]["display_name"] == "Bob"


async def test_search_is_case_insensitive_substring(client, db_session):
    admin = await _seed_admin(db_session)
    await _seed_user(db_session, "Zelda@Example.com", name="Zelda")

    resp = await client.get(SEARCH_URL, params={"email": "ZELDA"}, headers=_auth_header(admin.id))

    assert resp.status_code == 200, resp.text
    # An uppercase query matches the mixed-case stored email (ilike); the stored
    # address is returned verbatim.
    assert [row["email"] for row in resp.json()] == ["Zelda@Example.com"]


async def test_search_excludes_soft_deleted_accounts(client, db_session):
    from datetime import datetime, timezone

    admin = await _seed_admin(db_session)
    await _seed_user(
        db_session, "gone@example.com", name="Gone", deleted_at=datetime.now(timezone.utc)
    )

    resp = await client.get(SEARCH_URL, params={"email": "gone"}, headers=_auth_header(admin.id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ========================================================================== #
# DELETE /admin/users/{id} — authorization / guards
# ========================================================================== #


async def test_delete_unauthenticated_returns_401(client, db_session):
    target = await _seed_user(db_session, "target@example.com")

    resp = await client.delete(_delete_url(target.id))

    assert resp.status_code == 401, resp.text


async def test_delete_non_admin_returns_403(client, db_session):
    plain = await _seed_user(db_session, "plain@example.com")
    target = await _seed_user(db_session, "target@example.com")
    target_id = target.id

    resp = await client.delete(_delete_url(target.id), headers=_auth_header(plain.id))

    assert resp.status_code == 403, resp.text
    # Target untouched.
    assert await _count(db_session, User, id=target_id) == 1


async def test_delete_self_returns_409(client, db_session):
    admin = await _seed_admin(db_session)
    admin_id = admin.id

    resp = await client.delete(_delete_url(admin.id), headers=_auth_header(admin.id))

    assert resp.status_code == 409, resp.text
    # The admin account is NOT deleted.
    assert await _count(db_session, User, id=admin_id) == 1


async def test_delete_unknown_user_returns_404(client, db_session):
    admin = await _seed_admin(db_session)

    resp = await client.delete(_delete_url(uuid.uuid4()), headers=_auth_header(admin.id))

    assert resp.status_code == 404, resp.text


async def test_delete_already_soft_deleted_user_returns_404(client, db_session):
    from datetime import datetime, timezone

    admin = await _seed_admin(db_session)
    ghost = await _seed_user(db_session, "ghost@example.com", deleted_at=datetime.now(timezone.utc))

    resp = await client.delete(_delete_url(ghost.id), headers=_auth_header(admin.id))

    assert resp.status_code == 404, resp.text


# ========================================================================== #
# DELETE /admin/users/{id} — happy path: global hard-delete cascade
# ========================================================================== #


async def test_delete_hard_deletes_user_and_all_personal_data(client, db_session):
    admin = await _seed_admin(db_session)
    organizer = await _seed_user(db_session, "org@example.com", name="Org")
    target = await _seed_user(db_session, "bad@example.com", name="BadActor")

    # A league owned by the organizer, with the target as a member, plus a round
    # in which the target submitted, voted, and left a note.
    league = Club(
        name="A Club",
        organizer_id=organizer.id,
        total_mixes=3,
        votes_per_player=3,
        state="active",
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=organizer.id))
    db_session.add(ClubMember(club_id=league.id, user_id=target.id))
    round_ = Mix(club_id=league.id, mix_number=1, theme="t", state="closed")
    db_session.add(round_)
    await db_session.flush()
    submission = Submission(
        mix_id=round_.id,
        user_id=target.id,
        isrc="USABC1234567",
        title="song",
        artist="Artist",
        participation_mode="playing",
    )
    db_session.add(submission)
    await db_session.flush()
    db_session.add(Vote(mix_id=round_.id, voter_id=target.id, submission_id=submission.id))
    db_session.add(
        Note(
            mix_id=round_.id,
            author_id=target.id,
            submission_id=submission.id,
            body="a note",
        )
    )
    # A session for the target and an invite the target created.
    db_session.add(
        Session(
            user_id=target.id,
            refresh_token_hash="hash-" + uuid.uuid4().hex,
            device_hint="x",
        )
    )
    db_session.add(
        Invite(
            club_id=league.id,
            created_by=target.id,
            token="tok_" + uuid.uuid4().hex,
        )
    )
    await db_session.commit()

    target_id = target.id
    organizer_id = organizer.id
    submission_id = submission.id

    resp = await client.delete(_delete_url(target.id), headers=_auth_header(admin.id))

    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    db_session.expire_all()
    # The user and all of their personal data are gone — zero orphans.
    assert await _count(db_session, User, id=target_id) == 0
    assert await _count(db_session, Session, user_id=target_id) == 0
    assert await _count(db_session, ClubMember, user_id=target_id) == 0
    assert await _count(db_session, Submission, user_id=target_id) == 0
    assert await _count(db_session, Vote, voter_id=target_id) == 0
    assert await _count(db_session, Note, author_id=target_id) == 0
    assert await _count(db_session, Invite, created_by=target_id) == 0
    # No orphaned vote/note pointing at the deleted submission.
    assert await _count(db_session, Vote, submission_id=submission_id) == 0
    # Co-members are untouched; the organizer and league survive.
    assert await _count(db_session, User, id=organizer_id) == 1
    assert await _count(db_session, ClubMember, user_id=organizer_id) == 1


async def test_delete_nulls_organizer_fk_on_targets_leagues(client, db_session):
    # If the bad actor organized a league, the league survives with organizer_id
    # nulled (mirrors the purge job), rather than being deleted.
    admin = await _seed_admin(db_session)
    target = await _seed_user(db_session, "bad@example.com")
    league = Club(
        name="Orphaned Club",
        organizer_id=target.id,
        total_mixes=3,
        votes_per_player=3,
        state="complete",
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=target.id))
    await db_session.commit()

    league_id = league.id

    resp = await client.delete(_delete_url(target.id), headers=_auth_header(admin.id))
    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    surviving = await db_session.scalar(select(Club).where(Club.id == league_id))
    assert surviving is not None
    assert surviving.organizer_id is None
