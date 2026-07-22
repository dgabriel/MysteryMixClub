"""Co-organizer parity smoke tests (MYS-99).

``_load_club_as_organizer`` (in ``app.api.routes.clubs``, reused by
``app.api.routes.mixes``) now admits either the club's fixed
``organizer_id`` OR an active member promoted to ``role == "admin"``. These
tests exercise a co-organizer (never the fixed organizer) across every call
site that helper gates: club update, mix creation, mix update, member
removal, invite revocation, and club deletion — plus a closing regression
proving the fixed organizer's own access is unnarrowed by any of this.
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.invite import Invite
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.user import User

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


def _club_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}"


def _mixes_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}/mixes"


def _mix_url(mix_id) -> str:
    return f"/api/v1/mixes/{mix_id}"


def _remove_url(club_id, user_id) -> str:
    return f"/api/v1/clubs/{club_id}/members/{user_id}"


def _invites_url(club_id) -> str:
    return f"/api/v1/clubs/{club_id}/invites"


def _revoke_invite_url(club_id, invite_id) -> str:
    return f"/api/v1/clubs/{club_id}/invites/{invite_id}"


# ========================================================================== #
# Club update (PATCH /clubs/:id)
# ========================================================================== #


async def test_co_organizer_can_update_club(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, name="Old Name")
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    resp = await client.patch(
        _club_url(club.id),
        headers=_auth_header(co_organizer.id),
        json={"name": "Updated by Co-Organizer"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Updated by Co-Organizer"


# ========================================================================== #
# Mix creation (POST /clubs/:id/mixes)
# ========================================================================== #


async def test_co_organizer_can_create_a_mix(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, total_mixes=3, current_mix=0)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    resp = await client.post(
        _mixes_url(club.id),
        headers=_auth_header(co_organizer.id),
        json={"theme": "co-organizer picks"},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["theme"] == "co-organizer picks"


# ========================================================================== #
# Mix update (PATCH /mixes/:id)
# ========================================================================== #


async def test_co_organizer_can_update_a_mix(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, total_mixes=3, current_mix=1)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")
    mix_ = Mix(club_id=club.id, mix_number=1, state="pending")
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)

    resp = await client.patch(
        _mix_url(mix_.id),
        headers=_auth_header(co_organizer.id),
        json={"theme": "renamed by co-organizer"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == "renamed by co-organizer"


# ========================================================================== #
# Member removal (DELETE /clubs/:id/members/:userId)
# ========================================================================== #


async def test_co_organizer_can_remove_another_member(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, club, target)

    resp = await client.delete(
        _remove_url(club.id, target.id),
        headers=_auth_header(co_organizer.id),
    )

    assert resp.status_code == 204, resp.text

    club_id = club.id
    target_id = target.id
    db_session.expire_all()
    membership = await db_session.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == target_id)
    )
    assert membership is not None
    assert membership.removed_at is not None


# ========================================================================== #
# Invite revocation (DELETE /clubs/:id/invites/:inviteId)
# ========================================================================== #


async def test_co_organizer_can_revoke_an_invite(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    invite = Invite(
        club_id=club.id,
        created_by=organizer.id,
        token="co-organizer-revoke-token",
        expires_at=None,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    invite_id = invite.id

    resp = await client.delete(
        _revoke_invite_url(club.id, invite_id),
        headers=_auth_header(co_organizer.id),
    )

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(Invite).where(Invite.id == invite_id)) is None


# ========================================================================== #
# Club deletion (DELETE /clubs/:id)
# ========================================================================== #


async def test_co_organizer_can_delete_the_club(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")

    club_id = club.id

    resp = await client.delete(_club_url(club.id), headers=_auth_header(co_organizer.id))

    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == club_id)) is None


# ========================================================================== #
# Regression — the fixed organizer's own access is unnarrowed
# ========================================================================== #


async def test_fixed_organizer_retains_full_access_alongside_a_co_organizer(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    club = await _seed_club(db_session, organizer, name="Old Name", total_mixes=3)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, club, co_organizer, role="admin")
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, club, target)

    # Club update.
    patch_resp = await client.patch(
        _club_url(club.id),
        headers=_auth_header(organizer.id),
        json={"name": "Renamed by Organizer"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # Mix creation.
    create_resp = await client.post(
        _mixes_url(club.id),
        headers=_auth_header(organizer.id),
        json={"theme": "organizer picks"},
    )
    assert create_resp.status_code == 201, create_resp.text
    mix_id = create_resp.json()["id"]

    # Mix update. A freshly created mix opens for submissions immediately
    # (theme/description lock once open — see mixes.py); deadlines stay
    # editable, so exercise the update via a deadline field instead.
    update_resp = await client.patch(
        _mix_url(mix_id),
        headers=_auth_header(organizer.id),
        json={"submission_deadline": "2026-08-01T00:00:00Z"},
    )
    assert update_resp.status_code == 200, update_resp.text

    # Member removal.
    remove_resp = await client.delete(
        _remove_url(club.id, target.id),
        headers=_auth_header(organizer.id),
    )
    assert remove_resp.status_code == 204, remove_resp.text

    # Club deletion.
    delete_resp = await client.delete(_club_url(club.id), headers=_auth_header(organizer.id))
    assert delete_resp.status_code == 204, delete_resp.text
