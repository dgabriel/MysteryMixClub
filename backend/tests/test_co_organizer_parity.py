"""Co-organizer parity smoke tests (MYS-99).

``_load_league_as_organizer`` (in ``app.api.routes.leagues``, reused by
``app.api.routes.rounds``) now admits either the league's fixed
``organizer_id`` OR an active member promoted to ``role == "admin"``. These
tests exercise a co-organizer (never the fixed organizer) across every call
site that helper gates: league update, round creation, round update, member
removal, invite revocation, and league deletion — plus a closing regression
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


async def _seed_league(db_session, organizer: User, **overrides) -> Club:
    defaults = {
        "name": "Summer Bangers",
        "description": "A league for hot tracks",
        "organizer_id": organizer.id,
        "total_mixes": 6,
        "votes_per_player": 5,
        "current_mix": 0,
        "state": "active",
    }
    defaults.update(overrides)
    league = Club(**defaults)
    db_session.add(league)
    await db_session.flush()
    db_session.add(ClubMember(club_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _seed_member(db_session, league: Club, user: User, **overrides) -> ClubMember:
    defaults = {"club_id": league.id, "user_id": user.id}
    defaults.update(overrides)
    member = ClubMember(**defaults)
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _league_url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}"


def _rounds_url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}/mixes"


def _round_url(round_id) -> str:
    return f"/api/v1/mixes/{round_id}"


def _remove_url(league_id, user_id) -> str:
    return f"/api/v1/clubs/{league_id}/members/{user_id}"


def _invites_url(league_id) -> str:
    return f"/api/v1/clubs/{league_id}/invites"


def _revoke_invite_url(league_id, invite_id) -> str:
    return f"/api/v1/clubs/{league_id}/invites/{invite_id}"


# ========================================================================== #
# Club update (PATCH /leagues/:id)
# ========================================================================== #


async def test_co_organizer_can_update_league(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, name="Old Name")
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    resp = await client.patch(
        _league_url(league.id),
        headers=_auth_header(co_organizer.id),
        json={"name": "Updated by Co-Organizer"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Updated by Co-Organizer"


# ========================================================================== #
# Mix creation (POST /leagues/:id/rounds)
# ========================================================================== #


async def test_co_organizer_can_create_a_round(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, total_mixes=3, current_mix=0)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    resp = await client.post(
        _rounds_url(league.id),
        headers=_auth_header(co_organizer.id),
        json={"theme": "co-organizer picks"},
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["theme"] == "co-organizer picks"


# ========================================================================== #
# Mix update (PATCH /rounds/:id)
# ========================================================================== #


async def test_co_organizer_can_update_a_round(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, total_mixes=3, current_mix=1)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")
    round_ = Mix(club_id=league.id, mix_number=1, state="pending")
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)

    resp = await client.patch(
        _round_url(round_.id),
        headers=_auth_header(co_organizer.id),
        json={"theme": "renamed by co-organizer"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == "renamed by co-organizer"


# ========================================================================== #
# Member removal (DELETE /leagues/:id/members/:userId)
# ========================================================================== #


async def test_co_organizer_can_remove_another_member(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, league, target)

    resp = await client.delete(
        _remove_url(league.id, target.id),
        headers=_auth_header(co_organizer.id),
    )

    assert resp.status_code == 204, resp.text

    league_id = league.id
    target_id = target.id
    db_session.expire_all()
    membership = await db_session.scalar(
        select(ClubMember).where(ClubMember.club_id == league_id, ClubMember.user_id == target_id)
    )
    assert membership is not None
    assert membership.removed_at is not None


# ========================================================================== #
# Invite revocation (DELETE /leagues/:id/invites/:inviteId)
# ========================================================================== #


async def test_co_organizer_can_revoke_an_invite(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    invite = Invite(
        club_id=league.id,
        created_by=organizer.id,
        token="co-organizer-revoke-token",
        expires_at=None,
    )
    db_session.add(invite)
    await db_session.commit()
    await db_session.refresh(invite)
    invite_id = invite.id

    resp = await client.delete(
        _revoke_invite_url(league.id, invite_id),
        headers=_auth_header(co_organizer.id),
    )

    assert resp.status_code == 204, resp.text

    db_session.expire_all()
    assert await db_session.scalar(select(Invite).where(Invite.id == invite_id)) is None


# ========================================================================== #
# Club deletion (DELETE /leagues/:id)
# ========================================================================== #


async def test_co_organizer_can_delete_the_league(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")

    league_id = league.id

    resp = await client.delete(_league_url(league.id), headers=_auth_header(co_organizer.id))

    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    assert await db_session.scalar(select(Club).where(Club.id == league_id)) is None


# ========================================================================== #
# Regression — the fixed organizer's own access is unnarrowed
# ========================================================================== #


async def test_fixed_organizer_retains_full_access_alongside_a_co_organizer(client, db_session):
    organizer = await _seed_user(db_session, email="org@example.com", display_name="Org")
    league = await _seed_league(db_session, organizer, name="Old Name", total_mixes=3)
    co_organizer = await _seed_user(db_session, email="co@example.com", display_name="Co")
    await _seed_member(db_session, league, co_organizer, role="admin")
    target = await _seed_user(db_session, email="target@example.com", display_name="Target")
    await _seed_member(db_session, league, target)

    # Club update.
    patch_resp = await client.patch(
        _league_url(league.id),
        headers=_auth_header(organizer.id),
        json={"name": "Renamed by Organizer"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # Mix creation.
    create_resp = await client.post(
        _rounds_url(league.id),
        headers=_auth_header(organizer.id),
        json={"theme": "organizer picks"},
    )
    assert create_resp.status_code == 201, create_resp.text
    round_id = create_resp.json()["id"]

    # Mix update. A freshly created round opens for submissions immediately
    # (theme/description lock once open — see rounds.py); deadlines stay
    # editable, so exercise the update via a deadline field instead.
    update_resp = await client.patch(
        _round_url(round_id),
        headers=_auth_header(organizer.id),
        json={"submission_deadline": "2026-08-01T00:00:00Z"},
    )
    assert update_resp.status_code == 200, update_resp.text

    # Member removal.
    remove_resp = await client.delete(
        _remove_url(league.id, target.id),
        headers=_auth_header(organizer.id),
    )
    assert remove_resp.status_code == 204, remove_resp.text

    # Club deletion.
    delete_resp = await client.delete(_league_url(league.id), headers=_auth_header(organizer.id))
    assert delete_resp.status_code == 204, delete_resp.text
