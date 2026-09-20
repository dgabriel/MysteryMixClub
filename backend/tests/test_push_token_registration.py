"""Tests for POST/DELETE /users/me/push-token (MysteryMixClub-4vii.25).

PKs are captured into locals before any expire_all (project MissingGreenlet
gotcha).
"""

from sqlalchemy import delete, select

from app.auth.jwt import create_access_token
from app.models.device_push_token import DevicePushToken
from app.models.user import User

REGISTER_URL = "/api/v1/users/me/push-token"


def _auth_header(user_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# POST — register
# --------------------------------------------------------------------------- #


async def test_register_creates_a_new_row(client, db_session):
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id

    resp = await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    row = await db_session.scalar(
        select(DevicePushToken).where(DevicePushToken.device_token == "device-abc")
    )
    assert row is not None
    assert row.user_id == user_id
    assert row.platform == "ios"


async def test_register_is_idempotent_for_the_same_user(client, db_session):
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id

    await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )
    resp = await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    rows = (
        await db_session.scalars(
            select(DevicePushToken).where(DevicePushToken.device_token == "device-abc")
        )
    ).all()
    assert len(rows) == 1


async def test_re_registering_restamps_updated_at_even_for_the_same_user(client, db_session):
    # A dead-token verdict from APNs only retires a registration that predates
    # it (MysteryMixClub-4vii.33), so a device that just re-registered must
    # read as newer -- even though nothing else about the row changed.
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id
    await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )
    first = await db_session.scalar(
        select(DevicePushToken.updated_at).where(DevicePushToken.device_token == "device-abc")
    )
    assert first is not None

    resp = await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    second = await db_session.scalar(
        select(DevicePushToken.updated_at).where(DevicePushToken.device_token == "device-abc")
    )
    assert second is not None and second > first


async def test_register_after_the_row_was_retired_registers_again(client, db_session):
    # A registration that follows a retire (row already gone) simply inserts,
    # rather than updating nothing or raising. This pins that behaviour; it is
    # sequential, so it cannot itself reproduce the concurrent race the single
    # INSERT ... ON CONFLICT statement exists to close.
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id
    await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )
    await db_session.execute(delete(DevicePushToken))
    await db_session.commit()

    resp = await client.post(
        REGISTER_URL, json={"device_token": "device-abc"}, headers=_auth_header(user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    row = await db_session.scalar(
        select(DevicePushToken).where(DevicePushToken.device_token == "device-abc")
    )
    assert row is not None and row.user_id == user_id


async def test_register_reassigns_a_token_from_a_different_user(client, db_session):
    # Same device, signed out and back in as someone else -- the token
    # follows the current caller, not stays with the original registrant.
    first_user = await _seed_user(db_session, "first@example.com")
    second_user = await _seed_user(db_session, "second@example.com")
    second_user_id = second_user.id

    await client.post(
        REGISTER_URL, json={"device_token": "shared-device"}, headers=_auth_header(first_user.id)
    )
    resp = await client.post(
        REGISTER_URL, json={"device_token": "shared-device"}, headers=_auth_header(second_user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    rows = (
        await db_session.scalars(
            select(DevicePushToken).where(DevicePushToken.device_token == "shared-device")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].user_id == second_user_id


async def test_register_allows_the_same_user_to_have_multiple_devices(client, db_session):
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id

    await client.post(
        REGISTER_URL, json={"device_token": "device-1"}, headers=_auth_header(user_id)
    )
    resp = await client.post(
        REGISTER_URL, json={"device_token": "device-2"}, headers=_auth_header(user_id)
    )

    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    rows = (
        await db_session.scalars(select(DevicePushToken).where(DevicePushToken.user_id == user_id))
    ).all()
    assert {r.device_token for r in rows} == {"device-1", "device-2"}


async def test_register_requires_auth(client):
    resp = await client.post(REGISTER_URL, json={"device_token": "device-abc"})
    assert resp.status_code == 401, resp.text


async def test_register_rejects_an_empty_token(client, db_session):
    user = await _seed_user(db_session, "member@example.com")

    resp = await client.post(REGISTER_URL, json={"device_token": ""}, headers=_auth_header(user.id))

    assert resp.status_code == 422, resp.text


# --------------------------------------------------------------------------- #
# DELETE — unregister
# --------------------------------------------------------------------------- #


async def test_unregister_deletes_the_caller_s_own_token(client, db_session):
    user = await _seed_user(db_session, "member@example.com")
    user_id = user.id
    db_session.add(DevicePushToken(user_id=user_id, device_token="device-abc"))
    await db_session.commit()

    resp = await client.request(
        "DELETE",
        REGISTER_URL,
        params={"device_token": "device-abc"},
        headers=_auth_header(user_id),
    )

    assert resp.status_code == 204, resp.text
    db_session.expire_all()
    row = await db_session.scalar(
        select(DevicePushToken).where(DevicePushToken.device_token == "device-abc")
    )
    assert row is None


async def test_unregister_does_not_touch_another_user_s_token(client, db_session):
    owner = await _seed_user(db_session, "owner@example.com")
    other = await _seed_user(db_session, "other@example.com")
    owner_id = owner.id
    db_session.add(DevicePushToken(user_id=owner_id, device_token="device-abc"))
    await db_session.commit()

    resp = await client.request(
        "DELETE",
        REGISTER_URL,
        params={"device_token": "device-abc"},
        headers=_auth_header(other.id),
    )

    assert resp.status_code == 204, resp.text  # no-op, not an error
    db_session.expire_all()
    row = await db_session.scalar(
        select(DevicePushToken).where(DevicePushToken.device_token == "device-abc")
    )
    assert row is not None
    assert row.user_id == owner_id


async def test_unregister_a_nonexistent_token_is_a_no_op(client, db_session):
    user = await _seed_user(db_session, "member@example.com")

    resp = await client.request(
        "DELETE",
        REGISTER_URL,
        params={"device_token": "never-existed"},
        headers=_auth_header(user.id),
    )

    assert resp.status_code == 204, resp.text


async def test_unregister_requires_auth(client):
    resp = await client.request("DELETE", REGISTER_URL, params={"device_token": "device-abc"})
    assert resp.status_code == 401, resp.text
