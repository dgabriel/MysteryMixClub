"""Tests for MYS-80: 20-member club cap enforced on join.

Covers:
  POST /api/v1/invites/{token}/accept  — 409 at cap, boundary at 19->20,
                                          removed members excluded from the
                                          count, concurrent race for the last
                                          slot (MYS-32-style guard)
  GET  /api/v1/auth/verify             — new-signup-via-full-club-invite is
                                          hard-blocked (409, no account
                                          created); existing-user-via-full-
                                          club-invite still logs in, join
                                          silently skipped

The organizer counts toward the cap like any other member (their own
club_members row is created alongside the club), matching the existing
member_count convention on the invite preview endpoint.

See technical-design.md §6 (club_members), §7 (Invites, Auth).
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.session import Session
from app.models.user import User

ACCEPT_URL_TMPL = "/api/v1/invites/{token}/accept"
PREVIEW_URL_TMPL = "/api/v1/invites/{token}"
REQUEST_URL = "/api/v1/auth/request"
VERIFY_URL = "/api/v1/auth/verify"

_CLUB_MEMBER_CAP = 20
_CLUB_FULL_MESSAGE = f"this club is full ({_CLUB_MEMBER_CAP} members)"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, **overrides) -> User:
    defaults = {"email": email, "display_name": "User"}
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer: User, **overrides) -> Club:
    """Insert a Club with the organizer as an active member (counts toward
    the cap, per the implementation's own comment)."""
    defaults = {
        "name": "Packed Club",
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


async def _seed_invite(db_session, club: Club, creator: User, **overrides) -> Invite:
    defaults = {
        "club_id": club.id,
        "created_by": creator.id,
        "token": "tok_" + uuid.uuid4().hex,
        "expires_at": None,
    }
    defaults.update(overrides)
    invite = Invite(**defaults)
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    return invite


async def _add_active_members(db_session, club: Club, n: int, *, prefix: str) -> None:
    """Seed ``n`` additional active club_members rows (fresh users)."""
    for i in range(n):
        user = User(email=f"{prefix}{i}@example.com", display_name=f"{prefix}{i}")
        db_session.add(user)
        await db_session.flush()
        db_session.add(ClubMember(club_id=club.id, user_id=user.id))
    await db_session.commit()


async def _add_removed_members(db_session, club: Club, n: int, *, prefix: str) -> None:
    """Seed ``n`` REMOVED (inactive) club_members rows — must not count
    toward the cap."""
    for i in range(n):
        user = User(email=f"{prefix}{i}@example.com", display_name=f"{prefix}{i}")
        db_session.add(user)
        await db_session.flush()
        db_session.add(
            ClubMember(
                club_id=club.id,
                user_id=user.id,
                removed_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _active_member_count(db_session, club_id) -> int:
    count = await db_session.scalar(
        select(func.count())
        .select_from(ClubMember)
        .where(ClubMember.club_id == club_id, ClubMember.removed_at.is_(None))
    )
    return count or 0


async def _request_link(client, email_spy, email: str, invite_token: str | None = None) -> str:
    body: dict[str, str] = {"email": email}
    if invite_token is not None:
        body["invite_token"] = invite_token
    resp = await client.post(REQUEST_URL, json=body)
    assert resp.status_code == 200, f"request -> {resp.status_code}: {resp.text}"
    _, link = email_spy.calls[-1]
    return link.split("token=")[1].split("&")[0]


# ========================================================================== #
# POST /invites/{token}/accept — cap enforcement
# ========================================================================== #


async def test_accept_at_cap_returns_409_with_exact_message(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    # organizer (1) + 19 more = 20 active members exactly.
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)
    joiner = await _seed_user(db_session, "overflow@example.com")

    club_id = club.id
    joiner_id = joiner.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    resp = await client.post(
        ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(joiner.id)
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _CLUB_FULL_MESSAGE

    # No membership row was created for the rejected joiner.
    db_session.expire_all()
    rows = (
        await db_session.scalars(
            select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == joiner_id)
        )
    ).all()
    assert rows == []
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP


async def test_accept_at_19_members_20th_join_succeeds(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    # organizer (1) + 18 more = 19 active members — exactly one slot open.
    await _add_active_members(db_session, club, 18, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)
    joiner = await _seed_user(db_session, "lastslot@example.com")

    club_id = club.id
    joiner_id = joiner.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP - 1

    resp = await client.post(
        ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(joiner.id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    members = (
        await db_session.scalars(
            select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == joiner_id)
        )
    ).all()
    assert len(members) == 1
    assert members[0].removed_at is None


async def test_removed_members_do_not_count_toward_cap(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    # organizer (1) + 18 active = 19 active, plus 5 REMOVED rows that must be
    # excluded from the cap count.
    await _add_active_members(db_session, club, 18, prefix="active")
    await _add_removed_members(db_session, club, 5, prefix="removed")
    invite = await _seed_invite(db_session, club, organizer)
    joiner = await _seed_user(db_session, "newcomer@example.com")

    club_id = club.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP - 1

    resp = await client.post(
        ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(joiner.id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP


async def test_preview_member_count_matches_cap_check_at_exactly_20(client, db_session):
    # Sanity: the preview's member_count (existing convention) and the cap
    # check agree on what "full" means.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)

    resp = await client.get(PREVIEW_URL_TMPL.format(token=invite.token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["member_count"] == _CLUB_MEMBER_CAP


async def test_already_active_member_can_still_accept_a_full_club(client, db_session):
    # Idempotent accept (MYS-135) must not be blocked by the cap — an
    # already-active member re-accepting is a no-op routed to the club, not
    # a rejected join.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)

    club_id = club.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    # The organizer is already an active member of this (full) club.
    resp = await client.post(
        ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(organizer.id)
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(club_id)


async def test_concurrent_accept_for_last_slot_only_one_joins(real_client, real_db_session):
    # MYS-80 concurrency guard: club at 19 active members (one slot open), two
    # different new users race for the accept endpoint. Only one may win the
    # last slot; the other must see 409, not a 21st member. Follows the same
    # asyncio.gather pattern as MYS-32's test_concurrent_accept_produces_
    # exactly_one_membership in test_invites_preview_accept.py.
    #
    # Uses real_client/real_db_session (genuinely separate real connections,
    # ADR 0005), not the default client/db_session: the two "concurrent"
    # requests below must actually contend for the with_for_update() row
    # lock on the club row, which requires two real connections/transactions
    # racing each other — the default fixtures share a single connection per
    # test, so they couldn't exercise this race at all.
    organizer = await _seed_user(real_db_session, "org@example.com")
    club = await _seed_club(real_db_session, organizer)
    await _add_active_members(real_db_session, club, 18, prefix="m")
    invite = await _seed_invite(real_db_session, club, organizer)
    racer_a = await _seed_user(real_db_session, "racer-a@example.com")
    racer_b = await _seed_user(real_db_session, "racer-b@example.com")

    club_id = club.id
    assert await _active_member_count(real_db_session, club_id) == _CLUB_MEMBER_CAP - 1

    resp_a, resp_b = await asyncio.gather(
        real_client.post(
            ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(racer_a.id)
        ),
        real_client.post(
            ACCEPT_URL_TMPL.format(token=invite.token), headers=_auth_header(racer_b.id)
        ),
    )

    statuses = sorted([resp_a.status_code, resp_b.status_code])
    assert statuses == [200, 409], (
        resp_a.status_code,
        resp_a.text,
        resp_b.status_code,
        resp_b.text,
    )

    real_db_session.expire_all()
    # The cap was never exceeded — exactly 20 active, never 21.
    assert await _active_member_count(real_db_session, club_id) == _CLUB_MEMBER_CAP


# ========================================================================== #
# GET /auth/verify — magic-link auto-join path
# ========================================================================== #


async def test_new_signup_via_full_club_invite_returns_409_no_account_created(
    client, email_spy, db_session
):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)
    token = invite.token

    club_id = club.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    raw = await _request_link(client, email_spy, "brandnew@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == _CLUB_FULL_MESSAGE

    # No orphaned user row, no session, cap unchanged.
    db_session.expire_all()
    new_user = await db_session.scalar(select(User).where(User.email == "brandnew@example.com"))
    assert new_user is None
    session_count = await db_session.scalar(select(func.count()).select_from(Session))
    assert session_count == 0
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP


async def test_existing_user_via_full_club_invite_still_logs_in_join_skipped(
    client, email_spy, db_session
):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)
    token = invite.token

    # An existing user, NOT currently a member of this (full) club.
    existing = await _seed_user(db_session, "resident@example.com")
    existing_id = existing.id
    club_id = club.id
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    raw = await _request_link(client, email_spy, "resident@example.com", invite_token=token)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

    # Login succeeds — no 409 surfaces to an existing user.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"access_token", "token_type"}
    assert body["access_token"]

    # Join was silently skipped: the user is NOT a member of the full club,
    # and the cap was not exceeded.
    db_session.expire_all()
    rows = (
        await db_session.scalars(
            select(ClubMember).where(
                ClubMember.club_id == club_id, ClubMember.user_id == existing_id
            )
        )
    ).all()
    assert rows == []
    assert await _active_member_count(db_session, club_id) == _CLUB_MEMBER_CAP

    # A real session was still created — this is a genuine successful login.
    session_count = await db_session.scalar(
        select(func.count()).select_from(Session).where(Session.user_id == existing_id)
    )
    assert session_count == 1


async def test_existing_user_via_full_club_invite_does_not_get_welcome_email(
    client, email_spy, db_session
):
    # Belt-and-suspenders on the "join silently skipped" behavior: since no
    # join happened, no club_joined welcome email should be queued either.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_active_members(db_session, club, 19, prefix="m")
    invite = await _seed_invite(db_session, club, organizer)
    token = invite.token

    await _seed_user(db_session, "resident2@example.com")

    raw = await _request_link(client, email_spy, "resident2@example.com", invite_token=token)
    sends_before = len(email_spy.sends)
    resp = await client.get(VERIFY_URL, params={"token": raw, "invite": token})

    assert resp.status_code == 200, resp.text
    # No new notification-style send was queued as a result of this call.
    # (queue_club_joined uses background_tasks; with ASGITransport these run
    # synchronously as part of request handling in this test client, so by
    # the time the response is returned any such send would already be
    # recorded.)
    assert len(email_spy.sends) == sends_before
