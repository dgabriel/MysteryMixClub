"""Registration vs logout on two REAL connections (MysteryMixClub-4vii.36, ADR 0034).

The rest of the suite runs each test inside one shared, rolled-back transaction
(ADR 0005), where two requests cannot genuinely contend for a row lock. The
guarantee "a registration can never recreate a row after logout" rests on exactly
that lock -- registration reads its session FOR UPDATE, logout / logout-all take
the same row FOR UPDATE -- so it is exercised here with the ``real_*`` fixtures
(real commits, real cross-connection blocking; ADR 0005 keeps these for this
purpose and pays a small TRUNCATE to clean up).

Each ordering is forced deterministically: a second connection takes the lock,
the request under test is started and shown to BLOCK behind it, then the lock is
released and the outcome asserted.

Two of the "registration commits first" tests stand in for the registration with
a hand-written FOR UPDATE plus insert: a request cannot be paused halfway through
its own transaction. The route itself is exercised by the tests where it is the
request that blocks, and by the unforced races.
"""

import asyncio
import random
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text, update

from app.auth.jwt import create_access_token
from app.auth.tokens import generate_token, hash_token
from app.jobs.purge_accounts import hard_delete_users
from app.models.device_push_token import DevicePushToken
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User

REGISTER_URL = "/api/v1/users/me/push-token"
LOGOUT_URL = "/api/v1/auth/logout"
LOGOUT_ALL_URL = "/api/v1/auth/logout-all"
# Long enough for a blocked request to have visibly not finished, short enough
# not to slow the suite.
_BLOCKED_FOR = 0.5


async def _login(db, email: str):
    user = User(email=email, display_name="")
    db.add(user)
    await db.commit()
    user_id = user.id
    raw = f"refresh-{uuid.uuid4()}"
    session = Session(user_id=user_id, refresh_token_hash=hash_token(raw))
    db.add(session)
    await db.commit()
    session_id = session.id
    headers = {"Authorization": f"Bearer {create_access_token(user_id, session_id)}"}
    return user_id, session_id, raw, headers


async def _device_tokens(factory) -> list[str]:
    async with factory() as db:
        return list((await db.execute(select(DevicePushToken.device_token))).scalars().all())


async def test_registration_that_commits_first_is_deleted_by_the_logout_that_waited(
    real_client, real_db_session, real_session_factory
):
    user_id, session_id, raw, _headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as registering:
        # The registration has passed its liveness check and holds the session
        # row FOR UPDATE, but has not committed yet.
        await registering.scalar(select(Session).where(Session.id == session_id).with_for_update())
        logout = asyncio.create_task(real_client.post(LOGOUT_URL, cookies={"refresh_token": raw}))
        await asyncio.sleep(_BLOCKED_FOR)
        assert not logout.done(), "logout must wait for the in-flight registration"

        registering.add(
            DevicePushToken(user_id=user_id, device_token="device-1", session_id=session_id)
        )
        await registering.commit()

    response = await asyncio.wait_for(logout, 10)

    assert response.status_code == 200
    # The row the registration just committed is removed by the logout behind it.
    assert await _device_tokens(real_session_factory) == []


async def test_registration_that_starts_after_logout_holds_the_lock_is_refused(
    real_client, real_db_session, real_session_factory
):
    _user_id, session_id, _raw, headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as logging_out:
        await logging_out.scalar(select(Session).where(Session.id == session_id).with_for_update())
        await logging_out.execute(
            update(Session)
            .where(Session.id == session_id)
            .values(invalidated_at=datetime.now(timezone.utc))
        )
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=headers)
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not register.done(), "registration must wait for the logout in progress"
        await logging_out.commit()

    response = await asyncio.wait_for(register, 10)

    # It re-reads the row after the logout committed and sees it signed out.
    assert response.status_code == 401
    assert await _device_tokens(real_session_factory) == []


async def test_logout_all_in_progress_also_refuses_a_waiting_registration(
    real_client, real_db_session, real_session_factory
):
    user_id, _session_id, _raw, headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as logging_out:
        await logging_out.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.invalidated_at.is_(None))
            .values(invalidated_at=datetime.now(timezone.utc))
        )
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=headers)
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not register.done()
        await logging_out.commit()

    response = await asyncio.wait_for(register, 10)

    assert response.status_code == 401
    assert await _device_tokens(real_session_factory) == []


async def test_registration_that_commits_first_is_deleted_by_the_logout_all_that_waited(
    real_client, real_db_session, real_session_factory
):
    user_id, session_id, raw, _headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as registering:
        await registering.scalar(select(Session).where(Session.id == session_id).with_for_update())
        logout_all = asyncio.create_task(
            real_client.post(LOGOUT_ALL_URL, cookies={"refresh_token": raw})
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not logout_all.done()
        registering.add(
            DevicePushToken(user_id=user_id, device_token="device-1", session_id=session_id)
        )
        await registering.commit()

    response = await asyncio.wait_for(logout_all, 10)

    assert response.status_code == 200
    assert await _device_tokens(real_session_factory) == []


async def test_a_registration_and_a_logout_racing_freely_never_leave_a_row_behind(
    real_client, real_db_session, real_session_factory
):
    # No forced ordering: whichever wins, the invariant is that once both have
    # finished no device remains for the logged-out session.
    for i in range(15):
        _uid, _sid, raw, headers = await _login(real_db_session, f"u{i}@example.com")
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": f"t{i}"}, headers=headers)
        )
        logout = asyncio.create_task(real_client.post(LOGOUT_URL, cookies={"refresh_token": raw}))
        registered, logged_out = await asyncio.gather(register, logout)

        assert logged_out.status_code == 200
        assert registered.status_code in (200, 401), registered.text

    assert await _device_tokens(real_session_factory) == []


# --------------------------------------------------------------------------- #
# Lock ORDER against account deletion (a deadlock the first version had)
# --------------------------------------------------------------------------- #
#
# `delete_me` updates the unique users.email (a key update, so it takes the row
# exclusively) and only afterwards updates the caller's sessions. Registration
# used to lock the session row FIRST and reach the users row later through the
# device insert's foreign key: opposite orders, so the two deadlocked. It now takes
# the users row first, in the same order as deletion.


async def test_registration_takes_the_user_row_before_the_session_row(
    real_client, real_db_session, real_session_factory
):
    user_id, session_id, _raw, headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as deleting, real_session_factory() as probe:
        # Someone holds the user row exclusively, as account deletion does.
        await deleting.execute(text("SELECT 1 FROM users WHERE id = :u FOR UPDATE"), {"u": user_id})
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=headers)
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not register.done(), "registration must wait for the user row"

        # While it waits it must not already be holding the session row: that is
        # exactly the lock the deleting side needs next. NOWAIT fails at once if
        # the row is locked, so this would raise under the old order.
        await probe.execute(
            text("SELECT 1 FROM sessions WHERE id = :s FOR UPDATE NOWAIT"), {"s": session_id}
        )
        await probe.rollback()

        await deleting.rollback()

    response = await asyncio.wait_for(register, 10)
    assert response.status_code == 200, response.text


async def test_account_deletion_in_progress_cannot_deadlock_a_waiting_registration(
    real_client, real_db_session, real_session_factory
):
    # The reported interleaving, followed exactly: deletion holds the user row,
    # a registration arrives, deletion then goes on to update the sessions.
    user_id, session_id, _raw, headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as deleting:
        await deleting.execute(
            text("UPDATE users SET email = :e, deleted_at = now() WHERE id = :u"),
            {"e": f"deleted+{user_id}@deleted.invalid", "u": user_id},
        )
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=headers)
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not register.done()

        # Would block forever (Postgres then aborts one side) if the registration
        # already held the session row.
        await asyncio.wait_for(
            deleting.execute(
                update(Session)
                .where(Session.id == session_id)
                .values(invalidated_at=datetime.now(timezone.utc))
            ),
            5,
        )
        await deleting.commit()

    response = await asyncio.wait_for(register, 10)

    assert response.status_code == 401  # the account is gone
    assert await _device_tokens(real_session_factory) == []


async def test_a_registration_and_an_account_deletion_racing_freely_never_error(
    real_client, real_db_session, real_session_factory
):
    for i in range(15):
        user_id, _sid, _raw, headers = await _login(real_db_session, f"del{i}@example.com")
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": f"t{i}"}, headers=headers)
        )
        delete = asyncio.create_task(real_client.delete("/api/v1/users/me", headers=headers))
        registered, deleted = await asyncio.gather(register, delete)

        assert deleted.status_code == 204, deleted.text
        assert registered.status_code in (200, 401), (registered.status_code, registered.text)

    # Whichever won, no device outlives a deleted account.
    assert await _device_tokens(real_session_factory) == []


# --------------------------------------------------------------------------- #
# The users-row lock's MODE, and the hard-delete path
# --------------------------------------------------------------------------- #


async def test_an_ordinary_profile_edit_never_blocks_a_registration(
    real_client, real_db_session, real_session_factory
):
    # The lock registration takes on the user row must be FOR KEY SHARE, which
    # does not conflict with a change to a NON-key column. SQLAlchemy compiles
    # `with_for_update(key_share=True)` alone to FOR NO KEY UPDATE, which DOES
    # conflict with one; this is the test that tells the two apart.
    user_id, _sid, _raw, headers = await _login(real_db_session, "a@example.com")
    async with real_session_factory() as editing:
        await editing.execute(
            text("UPDATE users SET display_name = 'edited' WHERE id = :u"), {"u": user_id}
        )  # uncommitted: the user row is now locked for a non-key update

        response = await asyncio.wait_for(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=headers), 5
        )

        assert response.status_code == 200, response.text
        await editing.rollback()


async def test_a_user_hard_deleted_while_registering_is_refused_not_a_500(
    real_client, real_db_session, real_session_factory
):
    # A token with no session, so nothing but the users lock stands between it
    # and the foreign key. The user row is deleted (uncommitted) when the request
    # arrives; once that commits the re-read finds NO row.
    user_id, _sid, _raw, _headers = await _login(real_db_session, "a@example.com")
    legacy = {"Authorization": f"Bearer {create_access_token(user_id)}"}
    async with real_session_factory() as deleting:
        await deleting.execute(text("DELETE FROM sessions WHERE user_id = :u"), {"u": user_id})
        await deleting.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        register = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": "device-1"}, headers=legacy)
        )
        await asyncio.sleep(_BLOCKED_FOR)
        assert not register.done()
        await deleting.commit()

    response = await asyncio.wait_for(register, 10)

    assert response.status_code == 401, response.text
    assert await _device_tokens(real_session_factory) == []


# --------------------------------------------------------------------------- #
# Session before device rows, for every writer that touches device rows
# --------------------------------------------------------------------------- #
#
# Logout, logout-all and a password reset take the session row and then delete
# its device rows. Account deletion and the hard delete used to delete the device
# rows first and update/delete the sessions after: the opposite order, and a real
# deadlock (found by review, reproduced with the real routes). This is a local
# ordering for the writers that touch device rows, not a global lock order (ADR
# 0034 "Known limits" lists what it does not cover). A third connection
# holds the device row so both requests queue on it in the order that produces the
# cycle (the account deletion first), then lets go.


async def _drain(*tasks: "asyncio.Task") -> list:
    """Wait for the tasks, but never forever: a deadlock must FAIL the test, not hang it."""
    done, pending = await asyncio.wait(tasks, timeout=20)
    for task in pending:
        task.cancel()
    assert not pending, "a request never finished: the two are deadlocked"
    return [task.result() for task in tasks]


async def _seed_bound_device(db, user_id, session_id, token="d1"):
    db.add(DevicePushToken(user_id=user_id, device_token=token, session_id=session_id))
    await db.commit()


@pytest.mark.parametrize("sign_out_url", [LOGOUT_URL, LOGOUT_ALL_URL])
async def test_a_sign_out_and_an_account_deletion_queued_on_the_device_row_do_not_deadlock(
    sign_out_url, real_client, real_db_session, real_session_factory
):
    user_id, session_id, raw, headers = await _login(real_db_session, "a@example.com")
    await _seed_bound_device(real_db_session, user_id, session_id)
    holder_cm = real_session_factory()
    holder = await holder_cm.__aenter__()
    tasks: list = []
    try:
        await holder.execute(
            text("SELECT 1 FROM device_push_tokens WHERE device_token = 'd1' FOR UPDATE")
        )
        delete = asyncio.create_task(real_client.delete("/api/v1/users/me", headers=headers))
        await asyncio.sleep(_BLOCKED_FOR)  # the deletion is queued first
        sign_out = asyncio.create_task(
            real_client.post(sign_out_url, cookies={"refresh_token": raw})
        )
        await asyncio.sleep(_BLOCKED_FOR)
        tasks = [delete, sign_out]
    finally:
        await holder.rollback()
        await holder_cm.__aexit__(None, None, None)

    deleted, signed_out = await _drain(*tasks)

    assert deleted.status_code == 204, deleted.text
    assert signed_out.status_code == 200, signed_out.text
    assert await _device_tokens(real_session_factory) == []


@pytest.mark.parametrize("sign_out_url", [LOGOUT_URL, LOGOUT_ALL_URL])
async def test_a_sign_out_and_a_hard_delete_queued_on_the_device_row_do_not_deadlock(
    sign_out_url, real_client, real_db_session, real_session_factory
):
    user_id, session_id, raw, _headers = await _login(real_db_session, "a@example.com")
    await _seed_bound_device(real_db_session, user_id, session_id)
    deleting_cm = real_session_factory()
    deleting = await deleting_cm.__aenter__()
    holder_cm = real_session_factory()
    holder = await holder_cm.__aenter__()
    tasks: list = []

    async def hard_delete() -> None:
        await hard_delete_users(deleting, [user_id], ["a@example.com"])
        await deleting.commit()

    try:
        await holder.execute(
            text("SELECT 1 FROM device_push_tokens WHERE device_token = 'd1' FOR UPDATE")
        )
        purge = asyncio.create_task(hard_delete())
        await asyncio.sleep(_BLOCKED_FOR)  # the hard delete is queued first
        sign_out = asyncio.create_task(
            real_client.post(sign_out_url, cookies={"refresh_token": raw})
        )
        await asyncio.sleep(_BLOCKED_FOR)
        tasks = [purge, sign_out]
    finally:
        await holder.rollback()
        await holder_cm.__aexit__(None, None, None)

    try:
        _purged, signed_out = await _drain(*tasks)
    finally:
        await deleting_cm.__aexit__(None, None, None)

    # The session was deleted out from under the sign-out, which is idempotent
    # (logout-all identifies the user through the same cookie, now gone, so 401).
    assert signed_out.status_code in (200, 401), signed_out.text
    assert await _device_tokens(real_session_factory) == []


async def test_a_sign_out_racing_an_account_deletion_never_errors(
    real_client, real_db_session, real_session_factory
):
    for i in range(20):
        user_id, session_id, raw, headers = await _login(real_db_session, f"race{i}@example.com")
        await _seed_bound_device(real_db_session, user_id, session_id, token=f"r{i}")
        delete = asyncio.create_task(real_client.delete("/api/v1/users/me", headers=headers))
        logout = asyncio.create_task(real_client.post(LOGOUT_URL, cookies={"refresh_token": raw}))
        deleted, logged_out = await _drain(delete, logout)

        assert deleted.status_code == 204, deleted.text
        assert logged_out.status_code == 200, logged_out.text

    assert await _device_tokens(real_session_factory) == []


async def test_the_user_facing_writers_of_devices_and_sessions_racing_together_never_error(
    real_client, real_db_session, real_session_factory
):
    # Each review round found a NEW pair of these taking locks in opposite orders,
    # so as a backstop fire every USER-FACING writer that touches device rows or
    # the session-liveness lock at one account at once, 25 rounds: register (two
    # sessions), unregister, logout, logout-all, password reset, refresh, password
    # login, profile edit, account deletion. Seeded, so a failure reproduces. Any
    # exception or 5xx fails it, a deadlock fails via the timeout instead of
    # hanging, and the END STATE is asserted: no registration may outlive its
    # session or its account.
    #
    # Deliberately NOT included (a scope decision, see ADR 0034 "Known limits"):
    # the admin eject / scheduled purge (`hard_delete_users`), and login with
    # pre-existing failed-attempt rows or Google/Apple identity relinking racing
    # account deletion. Those pairs take locks in an order that predates this work
    # and do not involve device rows.
    from datetime import timedelta

    from app.auth.passwords import hash_password

    rng = random.Random(20260920)
    for round_no in range(25):
        email = f"stress{round_no}@example.com"
        user = User(email=email, display_name="", password_hash=hash_password("an old password 1"))
        real_db_session.add(user)
        await real_db_session.commit()
        user_id = user.id
        sessions = []
        for _ in range(2):
            _uid, session_id, raw, headers = await _login_for(real_db_session, user_id)
            await _seed_bound_device(
                real_db_session, user_id, session_id, token=f"s{round_no}-{session_id}"
            )
            sessions.append((session_id, raw, headers))
        raw_reset = generate_token()
        real_db_session.add(
            PasswordResetToken(
                email=email,
                token_hash=hash_token(raw_reset),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        await real_db_session.commit()

        (sid_a, raw_a, headers_a), (sid_b, raw_b, headers_b) = sessions
        # Lazy, so only the chosen ones are ever started.
        operations = {
            "register-a": lambda: real_client.post(
                REGISTER_URL, json={"device_token": f"new-{round_no}"}, headers=headers_a
            ),
            "register-b": lambda: real_client.post(
                REGISTER_URL, json={"device_token": f"s{round_no}-{sid_b}"}, headers=headers_b
            ),
            "unregister": lambda: real_client.delete(
                REGISTER_URL, params={"device_token": f"s{round_no}-{sid_a}"}, headers=headers_a
            ),
            "logout": lambda: real_client.post(LOGOUT_URL, cookies={"refresh_token": raw_a}),
            "logout-all": lambda: real_client.post(
                LOGOUT_ALL_URL, cookies={"refresh_token": raw_b}
            ),
            "reset": lambda: real_client.post(
                "/api/v1/auth/reset-password",
                json={"token": raw_reset, "password": "a brand new password 2"},
            ),
            "refresh": lambda: real_client.post(
                "/api/v1/auth/refresh", cookies={"refresh_token": raw_a}
            ),
            "login": lambda: real_client.post(
                "/api/v1/auth/login", json={"email": email, "password": "an old password 1"}
            ),
            "patch": lambda: real_client.patch(
                "/api/v1/users/me", json={"display_name": "edited"}, headers=headers_b
            ),
            "delete-account": lambda: real_client.delete("/api/v1/users/me", headers=headers_b),
        }
        # A random subset, not always everything: account deletion, logout-all and
        # a password reset each remove ALL of a user's devices, so a round that
        # always included them could never show a device that survived a plain
        # logout, and the end-state check below would prove nothing. Logout is
        # always in, so it must remove session A's device whatever else runs.
        others = [name for name in operations if name != "logout"]
        chosen = ["logout", *rng.sample(others, rng.randint(2, len(others)))]
        rng.shuffle(chosen)
        tasks = [asyncio.ensure_future(operations[name]()) for name in chosen]
        done, pending = await asyncio.wait(tasks, timeout=30)
        for task in pending:
            task.cancel()
        assert not pending, f"round {round_no} ({chosen}): deadlocked (never finished)"
        for name, task in zip(chosen, tasks):
            outcome = task.result()  # any raised exception fails the test here
            assert outcome.status_code < 500, (round_no, name, outcome.status_code, outcome.text)

        # The product invariant: no zombie registration.
        async with real_session_factory() as check:
            signed_out_devices = (
                await check.execute(
                    text(
                        "SELECT d.device_token FROM device_push_tokens d "
                        "JOIN sessions s ON s.id = d.session_id "
                        "WHERE s.invalidated_at IS NOT NULL"
                    )
                )
            ).all()
            deleted_users_devices = (
                await check.execute(
                    text(
                        "SELECT d.device_token FROM device_push_tokens d "
                        "JOIN users u ON u.id = d.user_id WHERE u.deleted_at IS NOT NULL"
                    )
                )
            ).all()
        assert signed_out_devices == [], f"round {round_no}: a device outlived its session"
        assert deleted_users_devices == [], f"round {round_no}: a device outlived its account"


async def _login_for(db, user_id):
    """A session for an existing user: (user_id, session_id, raw refresh, headers)."""
    raw = f"refresh-{uuid.uuid4()}"
    session = Session(user_id=user_id, refresh_token_hash=hash_token(raw))
    db.add(session)
    await db.commit()
    session_id = session.id
    headers = {"Authorization": f"Bearer {create_access_token(user_id, session_id)}"}
    return user_id, session_id, raw, headers


async def test_concurrent_registrations_of_different_tokens_from_one_session_never_deadlock(
    real_client, real_db_session, real_session_factory
):
    # Token rotation: registering a new token deletes the session's other rows. With
    # two rows for one session ALREADY present (the dead token plus the live one, the
    # very pair rotation exists to fix), two concurrent registrations of different
    # tokens each locked their own row through the upsert and then waited on the
    # other's in the delete: a deadlock, a 500 for one of them. Registrations of one
    # session are serialized by the session row lock, so the last one simply wins.
    for round_no in range(12):
        user_id, session_id, _raw, headers = await _login(
            real_db_session, f"rot{round_no}@example.com"
        )
        await _seed_bound_device(real_db_session, user_id, session_id, token=f"a{round_no}")
        await _seed_bound_device(real_db_session, user_id, session_id, token=f"b{round_no}")
        first = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": f"a{round_no}"}, headers=headers)
        )
        second = asyncio.create_task(
            real_client.post(REGISTER_URL, json={"device_token": f"b{round_no}"}, headers=headers)
        )
        responses = await _drain(first, second)

        assert [r.status_code for r in responses] == [200, 200], (round_no, responses)

    # Whichever won each round, a session ends up with exactly one token.
    async with real_session_factory() as check:
        counts = (
            (
                await check.execute(
                    text("SELECT count(*) FROM device_push_tokens GROUP BY session_id")
                )
            )
            .scalars()
            .all()
        )
    assert counts == [1] * 12
