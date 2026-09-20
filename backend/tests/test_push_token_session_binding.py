"""Push registrations are bound to the login session (MysteryMixClub-4vii.36).

An access token stays valid for up to an hour after logout, and a registration
upload can be in flight when logout runs, so a plain "DELETE on logout" cannot
stop a late POST from recreating the row. These pin the guarantees that do: a
registration needs a live session, logout removes its session's devices in the
same transaction, and only a newer sign-in can take over a token.

Sessions are seeded directly (no email flow) so their ages are controlled. PKs
are captured into locals before any expire_all (project MissingGreenlet gotcha).

These run on the shared-transaction harness, so they pin the outcome of each
ordering. The row-lock behaviour itself (registration vs logout on two real
connections, both orders) is exercised in test_push_token_session_concurrency.py.

IMPORTANT for anything added here: give the table SEVERAL bound rows when a
conflict fires. A rule that "works" against a one-row table can be wrong against
a real one (the takeover subquery was once uncorrelated and returned a 500 as
soon as a second bound row existed, which single-row tests could not see).
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.auth.tokens import hash_token
from app.models.device_push_token import DevicePushToken
from app.models.session import Session
from app.models.user import User

REGISTER_URL = "/api/v1/users/me/push-token"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"
_NEUTRAL_401 = "not authenticated"


async def _user(db_session, email: str) -> uuid.UUID:
    user = User(email=email, display_name="")
    db_session.add(user)
    await db_session.commit()
    return user.id


async def _login(db_session, user_id: uuid.UUID, *, age: timedelta = timedelta(0)):
    """A session for `user_id`, `age` old. Returns (session_id, raw refresh
    token, a Bearer header carrying that session as its `sid`)."""
    raw = f"refresh-{uuid.uuid4()}"
    session = Session(
        user_id=user_id,
        refresh_token_hash=hash_token(raw),
        created_at=datetime.now(timezone.utc) - age,
    )
    db_session.add(session)
    await db_session.commit()
    return session.id, raw, {"Authorization": f"Bearer {create_access_token(user_id, session.id)}"}


async def _rows(db_session) -> dict[str, tuple[uuid.UUID, uuid.UUID | None]]:
    """device_token -> (owner user id, owning session id)."""
    db_session.expire_all()
    result = await db_session.execute(
        select(DevicePushToken.device_token, DevicePushToken.user_id, DevicePushToken.session_id)
    )
    return {token: (user_id, session_id) for token, user_id, session_id in result.all()}


async def _register(client, headers, token: str):
    return await client.post(REGISTER_URL, json={"device_token": token}, headers=headers)


# --------------------------------------------------------------------------- #
# A registration needs a live session
# --------------------------------------------------------------------------- #


async def test_registration_records_the_session_it_was_made_under(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    session_id, _raw, headers = await _login(db_session, user_id)

    resp = await _register(client, headers, "device-1")

    assert resp.status_code == 200, resp.text
    assert await _rows(db_session) == {"device-1": (user_id, session_id)}


async def test_a_logged_out_session_cannot_register(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    session_id, _raw, headers = await _login(db_session, user_id)
    session = await db_session.get(Session, session_id)
    session.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await _register(client, headers, "device-1")

    assert resp.status_code == 401
    assert resp.json()["detail"] == _NEUTRAL_401
    assert await _rows(db_session) == {}


async def test_an_expired_session_cannot_register(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    _sid, _raw, headers = await _login(db_session, user_id, age=timedelta(days=31))

    resp = await _register(client, headers, "device-1")

    assert resp.status_code == 401
    assert await _rows(db_session) == {}


async def test_a_session_that_belongs_to_someone_else_cannot_register(client, db_session):
    owner_id = await _user(db_session, "owner@example.com")
    other_id = await _user(db_session, "other@example.com")
    owner_session_id, _raw, _ = await _login(db_session, owner_id)
    # A token for `other` that names the owner's session.
    forged = {"Authorization": f"Bearer {create_access_token(other_id, owner_session_id)}"}

    resp = await _register(client, forged, "device-1")

    assert resp.status_code == 401
    assert await _rows(db_session) == {}


async def test_a_token_naming_no_such_session_is_refused(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    ghost = {"Authorization": f"Bearer {create_access_token(user_id, uuid.uuid4())}"}

    assert (await _register(client, ghost, "device-1")).status_code == 401


async def test_a_token_without_a_session_keeps_the_previous_behaviour(client, db_session):
    # Tokens minted before the claim existed (expiring within the hour of the
    # deploy) must not suddenly stop working.
    user_id = await _user(db_session, "a@example.com")
    legacy = {"Authorization": f"Bearer {create_access_token(user_id)}"}

    resp = await _register(client, legacy, "device-1")

    assert resp.status_code == 200, resp.text
    assert await _rows(db_session) == {"device-1": (user_id, None)}


# --------------------------------------------------------------------------- #
# Logout removes its session's devices, and only those
# --------------------------------------------------------------------------- #


async def test_logout_removes_the_devices_registered_under_that_session(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    _sid, raw, headers = await _login(db_session, user_id)
    await _register(client, headers, "device-1")

    resp = await client.post(LOGOUT_URL, cookies={"refresh_token": raw})

    assert resp.status_code == 200
    assert await _rows(db_session) == {}


async def test_logout_leaves_every_other_session_and_device_alone(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    other_id = await _user(db_session, "b@example.com")
    _s1, raw1, headers1 = await _login(db_session, user_id)  # this phone
    s2, _raw2, headers2 = await _login(db_session, user_id)  # the same user's other phone
    s3, _raw3, headers3 = await _login(db_session, other_id)  # someone else
    await _register(client, headers1, "phone-1")
    await _register(client, headers2, "phone-2")
    await _register(client, headers3, "someone-elses")

    await client.post(LOGOUT_URL, cookies={"refresh_token": raw1})

    assert await _rows(db_session) == {
        "phone-2": (user_id, s2),
        "someone-elses": (other_id, s3),
    }


async def test_logout_all_removes_every_device_of_that_user_and_no_one_elses(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    other_id = await _user(db_session, "b@example.com")
    _s1, raw1, headers1 = await _login(db_session, user_id)
    _s2, _raw2, headers2 = await _login(db_session, user_id)
    s3, _raw3, headers3 = await _login(db_session, other_id)
    await _register(client, headers1, "phone-1")
    await _register(client, headers2, "phone-2")
    await _register(client, headers3, "someone-elses")
    legacy = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    await _register(client, legacy, "legacy-phone")  # a row with no session at all

    resp = await client.post(LOGOUT_ALL_URL, cookies={"refresh_token": raw1})

    assert resp.status_code == 200
    assert await _rows(db_session) == {"someone-elses": (other_id, s3)}


# --------------------------------------------------------------------------- #
# The race: an upload that lands AFTER logout (or after the next account)
# --------------------------------------------------------------------------- #


async def test_a_delayed_upload_after_logout_cannot_recreate_the_registration(client, db_session):
    # The reviewer's reproduction: registration is in flight (its access token
    # was already issued), logout runs and its cleanup succeeds, then the
    # original upload finally lands. It must be refused, not resurrect the row.
    user_id = await _user(db_session, "a@example.com")
    _sid, raw, headers = await _login(db_session, user_id)
    await _register(client, headers, "device-1")
    await client.post(LOGOUT_URL, cookies={"refresh_token": raw})
    assert await _rows(db_session) == {}

    late = await _register(client, headers, "device-1")  # same old access token

    assert late.status_code == 401
    assert await _rows(db_session) == {}


async def test_a_delayed_upload_after_the_next_account_registered_cannot_take_the_device_back(
    client, db_session
):
    # Account A logs out; account B signs in on the same phone and registers it;
    # A's old upload then lands. B keeps the device.
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    _a_sid, a_raw, a_headers = await _login(db_session, a_id)
    await client.post(LOGOUT_URL, cookies={"refresh_token": a_raw})
    b_sid, _b_raw, b_headers = await _login(db_session, b_id)
    assert (await _register(client, b_headers, "the-phone")).status_code == 200

    late = await _register(client, a_headers, "the-phone")

    assert late.status_code == 401  # A's session is logged out
    assert await _rows(db_session) == {"the-phone": (b_id, b_sid)}


async def test_an_older_login_cannot_overwrite_a_newer_one_that_never_logged_out(
    client, db_session
):
    # No logout at all (e.g. a magic link opened while another account is signed
    # in): A's session is still live, but B's is newer, so A's late upload loses.
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    _a_sid, _a_raw, a_headers = await _login(db_session, a_id, age=timedelta(minutes=10))
    b_sid, _b_raw, b_headers = await _login(db_session, b_id)
    assert (await _register(client, b_headers, "the-phone")).status_code == 200

    late = await _register(client, a_headers, "the-phone")

    assert late.status_code == 409
    assert await _rows(db_session) == {"the-phone": (b_id, b_sid)}


async def test_a_newer_login_takes_the_device_over_from_an_older_one(client, db_session):
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    _a_sid, _a_raw, a_headers = await _login(db_session, a_id, age=timedelta(minutes=10))
    b_sid, _b_raw, b_headers = await _login(db_session, b_id)
    assert (await _register(client, a_headers, "the-phone")).status_code == 200

    resp = await _register(client, b_headers, "the-phone")

    assert resp.status_code == 200
    assert await _rows(db_session) == {"the-phone": (b_id, b_sid)}


async def test_the_same_session_can_re_register_its_own_device(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    sid, _raw, headers = await _login(db_session, user_id)

    assert (await _register(client, headers, "device-1")).status_code == 200
    assert (await _register(client, headers, "device-1")).status_code == 200

    assert await _rows(db_session) == {"device-1": (user_id, sid)}


async def test_a_token_without_a_session_cannot_take_a_device_a_session_owns(client, db_session):
    # A token minted before the claim existed has no session to compare, so it must
    # not overwrite (or unbind) a device that a session owns, however old or new.
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    a_sid, _raw, a_headers = await _login(db_session, a_id)
    assert (await _register(client, a_headers, "the-phone")).status_code == 200
    legacy_b = {"Authorization": f"Bearer {create_access_token(b_id)}"}

    resp = await _register(client, legacy_b, "the-phone")

    assert resp.status_code == 409
    assert await _rows(db_session) == {"the-phone": (a_id, a_sid)}  # still A's, still bound


async def test_a_token_without_a_session_can_register_and_re_register_an_unbound_device(
    client, db_session
):
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    legacy_a = {"Authorization": f"Bearer {create_access_token(a_id)}"}
    legacy_b = {"Authorization": f"Bearer {create_access_token(b_id)}"}

    assert (await _register(client, legacy_a, "the-phone")).status_code == 200  # a new device
    assert (await _register(client, legacy_a, "the-phone")).status_code == 200  # again
    assert (await _register(client, legacy_b, "the-phone")).status_code == 200  # an unbound one

    assert await _rows(db_session) == {"the-phone": (b_id, None)}


async def test_a_row_with_no_session_never_blocks_a_bound_registration(client, db_session):
    # A legacy/unbound row (no session) never blocks a bound registration.
    user_id = await _user(db_session, "a@example.com")
    legacy = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    await _register(client, legacy, "device-1")
    sid, _raw, headers = await _login(db_session, user_id)

    assert (await _register(client, headers, "device-1")).status_code == 200
    assert await _rows(db_session) == {"device-1": (user_id, sid)}


# --------------------------------------------------------------------------- #
# The real login and refresh flows mint the session id
# --------------------------------------------------------------------------- #


async def test_login_and_refresh_issue_tokens_that_name_their_session(
    client, email_spy, session_factory, db_session
):
    from app.auth.jwt import decode_access_token_session_id
    from tests.test_auth_logout import _request_link

    raw_link_token = await _request_link(client, email_spy, session_factory, "flow@example.com")
    verify = await client.get("/api/v1/auth/verify", params={"token": raw_link_token})
    assert verify.status_code == 200, verify.text
    refresh_cookie = verify.cookies.get("refresh_token")

    db_session.expire_all()
    session = await db_session.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(refresh_cookie))
    )
    assert session is not None
    session_id = session.id
    assert decode_access_token_session_id(verify.json()["access_token"]) == session_id

    refreshed = await client.post("/api/v1/auth/refresh", cookies={"refresh_token": refresh_cookie})
    assert refreshed.status_code == 200, refreshed.text
    assert decode_access_token_session_id(refreshed.json()["access_token"]) == session_id


async def test_that_login_token_registers_and_logout_then_removes_the_device(
    client, email_spy, session_factory, db_session
):
    from tests.test_auth_logout import _request_link

    raw_link_token = await _request_link(client, email_spy, session_factory, "flow2@example.com")
    verify = await client.get("/api/v1/auth/verify", params={"token": raw_link_token})
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    refresh_cookie = verify.cookies.get("refresh_token")

    assert (await _register(client, headers, "device-1")).status_code == 200
    assert "device-1" in await _rows(db_session)

    await client.post(LOGOUT_URL, cookies={"refresh_token": refresh_cookie})

    assert await _rows(db_session) == {}
    assert (await _register(client, headers, "device-1")).status_code == 401


# --------------------------------------------------------------------------- #
# The sid claim itself
# --------------------------------------------------------------------------- #


def test_sid_claim_round_trips_and_is_absent_when_not_given():
    from app.auth.jwt import decode_access_token, decode_access_token_session_id

    user_id, session_id = uuid.uuid4(), uuid.uuid4()

    with_sid = create_access_token(user_id, session_id)
    without = create_access_token(user_id)

    assert decode_access_token_session_id(with_sid) == session_id
    assert decode_access_token_session_id(without) is None
    # Adding the claim changes nothing for code that only reads the subject.
    assert decode_access_token(with_sid) == user_id


def test_a_malformed_sid_is_an_error_not_an_absent_claim():
    import pytest
    from jose import jwt as jose_jwt

    from app.auth.jwt import JWTError, decode_access_token_session_id
    from app.config import get_settings

    now = int(datetime.now(timezone.utc).timestamp())
    for bad in ("not-a-uuid", 123, ["x"]):
        forged = jose_jwt.encode(
            {"sub": str(uuid.uuid4()), "sid": bad, "iat": now, "exp": now + 60},
            get_settings().secret_key,
            algorithm="HS256",
        )
        with pytest.raises(JWTError):
            decode_access_token_session_id(forged)


async def test_a_token_with_a_malformed_sid_is_refused_at_registration(client, db_session):
    from jose import jwt as jose_jwt

    from app.config import get_settings

    user_id = await _user(db_session, "a@example.com")
    now = int(datetime.now(timezone.utc).timestamp())
    forged = jose_jwt.encode(
        {"sub": str(user_id), "sid": "not-a-uuid", "iat": now, "exp": now + 60},
        get_settings().secret_key,
        algorithm="HS256",
    )

    resp = await _register(client, {"Authorization": f"Bearer {forged}"}, "device-1")

    assert resp.status_code == 401
    assert await _rows(db_session) == {}


# --------------------------------------------------------------------------- #
# With SEVERAL bound rows in the table (the case a one-row table hides)
# --------------------------------------------------------------------------- #


async def _three_logins(db_session):
    """Three accounts with sessions oldest -> newest (60, 30, 1 minutes old),
    returning [(user_id, session_id, headers), ...]."""
    out = []
    for name, age in (("old", 60), ("mid", 30), ("new", 1)):
        uid = await _user(db_session, f"{name}@example.com")
        sid, _raw, headers = await _login(db_session, uid, age=timedelta(minutes=age))
        out.append((uid, sid, headers))
    return out


async def test_re_registering_own_device_works_when_other_bound_rows_exist(client, db_session):
    # A relaunch: the app re-registers its own token while other accounts'
    # devices are already registered. Was a 500 (CardinalityViolation) before
    # the takeover subquery was tied to the conflicting row.
    (old_id, old_sid, old_h), (mid_id, mid_sid, mid_h), _new = await _three_logins(db_session)
    assert (await _register(client, old_h, "d-old")).status_code == 200
    assert (await _register(client, mid_h, "d-mid")).status_code == 200

    assert (await _register(client, old_h, "d-old")).status_code == 200

    assert await _rows(db_session) == {"d-old": (old_id, old_sid), "d-mid": (mid_id, mid_sid)}


async def test_a_newer_login_takes_over_when_other_bound_rows_exist(client, db_session):
    (
        (old_id, old_sid, old_h),
        (mid_id, mid_sid, mid_h),
        (new_id, new_sid, new_h),
    ) = await _three_logins(db_session)
    await _register(client, old_h, "d-old")
    await _register(client, mid_h, "d-mid")

    assert (await _register(client, new_h, "d-old")).status_code == 200

    assert await _rows(db_session) == {"d-old": (new_id, new_sid), "d-mid": (mid_id, mid_sid)}


async def test_an_older_login_still_gets_409_not_500_with_other_bound_rows(client, db_session):
    (
        (old_id, old_sid, old_h),
        (mid_id, mid_sid, mid_h),
        (new_id, new_sid, new_h),
    ) = await _three_logins(db_session)
    await _register(client, old_h, "d-old")
    await _register(client, new_h, "d-new")

    late = await _register(client, mid_h, "d-new")  # a mid-aged login vs a newer owner

    assert late.status_code == 409
    assert await _rows(db_session) == {"d-old": (old_id, old_sid), "d-new": (new_id, new_sid)}


async def test_each_decision_reads_only_the_conflicting_rows_own_owner(client, db_session):
    # Decoys of every age must not influence the answer for a specific token.
    (
        (old_id, old_sid, old_h),
        (mid_id, mid_sid, mid_h),
        (new_id, new_sid, new_h),
    ) = await _three_logins(db_session)
    await _register(client, old_h, "held-by-old")
    await _register(client, new_h, "held-by-new")

    # mid may take what old holds, and may not take what new holds.
    assert (await _register(client, mid_h, "held-by-old")).status_code == 200
    assert (await _register(client, mid_h, "held-by-new")).status_code == 409

    assert await _rows(db_session) == {
        "held-by-old": (mid_id, mid_sid),
        "held-by-new": (new_id, new_sid),
    }


# --------------------------------------------------------------------------- #
# "Signed out everywhere" (logout-all, password reset) drops signed-out devices
# --------------------------------------------------------------------------- #


async def test_the_signed_out_device_sweep_keeps_a_device_of_a_still_live_session(db_session):
    # The window this guards: a brand-new login registers a device after the
    # sessions UPDATE's snapshot but before the DELETE. Its session is still
    # live, so its device must survive; signed-out and session-less ones go.
    from app.api.routes.auth import _drop_signed_out_devices

    user_id = await _user(db_session, "a@example.com")
    other_id = await _user(db_session, "b@example.com")
    dead_sid, _r1, _h1 = await _login(db_session, user_id)
    live_sid, _r2, _h2 = await _login(db_session, user_id)
    other_sid, _r3, _h3 = await _login(db_session, other_id)
    db_session.add_all(
        [
            DevicePushToken(user_id=user_id, device_token="of-dead", session_id=dead_sid),
            DevicePushToken(user_id=user_id, device_token="of-live", session_id=live_sid),
            DevicePushToken(user_id=user_id, device_token="of-none", session_id=None),
            DevicePushToken(user_id=other_id, device_token="of-other", session_id=other_sid),
        ]
    )
    dead = await db_session.get(Session, dead_sid)
    dead.invalidated_at = datetime.now(timezone.utc)
    await db_session.commit()

    await _drop_signed_out_devices(db_session, user_id)
    await db_session.commit()

    assert await _rows(db_session) == {
        "of-live": (user_id, live_sid),
        "of-other": (other_id, other_sid),
    }


async def test_password_reset_drops_the_devices_of_every_session_it_signs_out(client, db_session):
    from app.auth.passwords import hash_password
    from app.models.password_reset_token import PasswordResetToken
    from app.auth.tokens import generate_token

    user = User(
        email="pw@example.com", display_name="", password_hash=hash_password("old password 1")
    )
    db_session.add(user)
    await db_session.commit()
    user_id = user.id
    _sid, _raw, headers = await _login(db_session, user_id)
    other_id = await _user(db_session, "b@example.com")
    other_sid, _r, other_h = await _login(db_session, other_id)
    await _register(client, headers, "phone")
    await _register(client, other_h, "someone-elses")
    raw_reset = generate_token()
    db_session.add(
        PasswordResetToken(
            email="pw@example.com",
            token_hash=hash_token(raw_reset),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
    )
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw_reset, "password": "a brand new pass 2"}
    )

    assert resp.status_code == 200, resp.text
    assert await _rows(db_session) == {"someone-elses": (other_id, other_sid)}


# --------------------------------------------------------------------------- #
# Token rotation: one device token per login session (MysteryMixClub-4vii.37)
# --------------------------------------------------------------------------- #


async def test_a_new_token_from_the_same_session_replaces_the_one_it_supersedes(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    sid, _raw, headers = await _login(db_session, user_id)
    assert (await _register(client, headers, "token-1")).status_code == 200

    assert (await _register(client, headers, "token-2")).status_code == 200

    assert await _rows(db_session) == {"token-2": (user_id, sid)}


async def test_rotating_a_token_leaves_every_other_session_and_account_alone(client, db_session):
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    a_sid, _ra, a_headers = await _login(db_session, a_id)
    a2_sid, _ra2, a2_headers = await _login(db_session, a_id)  # the same user's other device
    b_sid, _rb, b_headers = await _login(db_session, b_id)
    await _register(client, a_headers, "a-token-1")
    await _register(client, a2_headers, "a2-token")
    await _register(client, b_headers, "b-token")

    await _register(client, a_headers, "a-token-2")

    assert await _rows(db_session) == {
        "a-token-2": (a_id, a_sid),
        "a2-token": (a_id, a2_sid),
        "b-token": (b_id, b_sid),
    }


async def test_re_registering_the_same_token_never_deletes_it(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    sid, _raw, headers = await _login(db_session, user_id)

    for _ in range(3):
        assert (await _register(client, headers, "token-1")).status_code == 200

    assert await _rows(db_session) == {"token-1": (user_id, sid)}


async def test_a_refused_stale_registration_does_not_delete_anything(client, db_session):
    # The older login's late upload is refused (409) BEFORE any supersede delete,
    # so it cannot remove the newer login's device either.
    a_id = await _user(db_session, "a@example.com")
    b_id = await _user(db_session, "b@example.com")
    a_sid, _ra, a_headers = await _login(db_session, a_id, age=timedelta(minutes=10))
    b_sid, _rb, b_headers = await _login(db_session, b_id)
    await _register(client, a_headers, "a-own-token")
    await _register(client, b_headers, "the-phone")

    late = await _register(client, a_headers, "the-phone")  # A is older than the owner B

    assert late.status_code == 409
    assert await _rows(db_session) == {
        "a-own-token": (a_id, a_sid),
        "the-phone": (b_id, b_sid),
    }


async def test_a_session_less_token_never_supersedes_anything(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    sid, _raw, headers = await _login(db_session, user_id)
    await _register(client, headers, "bound-token")
    legacy = {"Authorization": f"Bearer {create_access_token(user_id)}"}

    assert (await _register(client, legacy, "legacy-token")).status_code == 200

    assert await _rows(db_session) == {
        "bound-token": (user_id, sid),
        "legacy-token": (user_id, None),
    }


async def test_logout_after_rotations_leaves_nothing_behind(client, db_session):
    user_id = await _user(db_session, "a@example.com")
    _sid, raw, headers = await _login(db_session, user_id)
    for token in ("t1", "t2", "t3"):
        await _register(client, headers, token)

    await client.post(LOGOUT_URL, cookies={"refresh_token": raw})

    assert await _rows(db_session) == {}
