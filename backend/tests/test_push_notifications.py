"""Tests for app.services.push_notifications (MysteryMixClub-4vii.25).

`send_push` is exercised against a real `httpx.MockTransport` (no network,
mirrors test_apple_music.py's approach) covering the 200/retire/failed
outcome mapping and the unconfigured no-op. The recipient-gathering queries
run against the real test database (mirrors test_auth_google.py's own
membership/preference-filter tests) since they're plain SQL joins worth
proving against Postgres, not something worth faking. `queue_push_event` /
`send_push_event` are covered by monkeypatching `send_push` itself, since
their own job is "call send_push once per recipient with the right copy and
data", not re-proving the HTTP layer.
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.device_push_token import DevicePushToken
from app.models.mix import Mix
from app.models.user import User
from app.services.apple_push_token import ApplePushTokenService
from app.services.push_notifications import (
    _retire_device_token,
    _title_and_body,
    gather_push_deadline_recipients,
    gather_push_recipients,
    organizer_push_recipients,
    send_push,
    send_push_event,
)

_BUNDLE_ID = "com.mysterymixclub.app"
_TEAM_ID = "TEAM123456"
_KEY_ID = "KEY1234567"
# A real P-256 key so the token service can actually sign -- send_push's job
# is to send whatever valid token the service mints, not to re-verify ES256
# signing (that's apple_push_token's own test file's job).
_PRIVATE_KEY = (
    ec.generate_private_key(ec.SECP256R1())
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)


def _configured_token_service() -> ApplePushTokenService:
    return ApplePushTokenService(_TEAM_ID, _KEY_ID, _PRIVATE_KEY)


def _unconfigured_token_service() -> ApplePushTokenService:
    return ApplePushTokenService("", "", "")


def _client(status_code: int) -> httpx.AsyncClient:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)


def _erroring_client() -> httpx.AsyncClient:
    def dispatch(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("could not connect", request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)


# --------------------------------------------------------------------------- #
# send_push: outcome mapping
# --------------------------------------------------------------------------- #


async def test_send_push_200_is_ok():
    async with _client(200) as client:
        outcome = await send_push(
            client, _configured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )
    assert outcome == "ok"


@pytest.mark.parametrize("status_code", [400, 410])
async def test_send_push_dead_token_status_is_retire(status_code):
    async with _client(status_code) as client:
        outcome = await send_push(
            client, _configured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )
    assert outcome == "retire"


async def test_send_push_other_status_is_failed():
    async with _client(500) as client:
        outcome = await send_push(
            client, _configured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )
    assert outcome == "failed"


async def test_send_push_network_error_is_failed():
    async with _erroring_client() as client:
        outcome = await send_push(
            client, _configured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )
    assert outcome == "failed"


async def test_send_push_unconfigured_service_is_failed_without_a_request():
    calls = {"n": 0}

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0) as client:
        outcome = await send_push(
            client, _unconfigured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )

    assert outcome == "failed"
    assert calls["n"] == 0  # never even tried to reach APNs


async def test_send_push_request_carries_topic_and_payload():
    captured: dict = {}

    def dispatch(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0) as client:
        await send_push(
            client,
            _configured_token_service(),
            _BUNDLE_ID,
            "device-token",
            "The Mystery Mix Club",
            "Voting is open for Mystery Mix 4.",
            data={"club_id": "abc", "event": "voting_open"},
        )

    assert captured["headers"]["apns-topic"] == _BUNDLE_ID
    assert captured["headers"]["apns-push-type"] == "alert"
    assert b"Voting is open" in captured["body"]
    assert b"abc" in captured["body"]


# --------------------------------------------------------------------------- #
# Restrained lock-screen copy
# --------------------------------------------------------------------------- #


def _club(**overrides) -> Club:
    defaults = dict(
        id=uuid.uuid4(),
        name="The Mystery Mix Club",
        organizer_id=uuid.uuid4(),
        total_mixes=3,
        votes_per_player=3,
    )
    defaults.update(overrides)
    return Club(**defaults)


def _mix(**overrides) -> Mix:
    defaults = dict(
        id=uuid.uuid4(), club_id=uuid.uuid4(), mix_number=4, theme="80s one-hit wonders"
    )
    defaults.update(overrides)
    return Mix(**defaults)


@pytest.mark.parametrize(
    "event",
    [
        "submission_open",
        "voting_open",
        "mix_closed",
        "voting_extended",
        "needs_theme",
        "club_complete",
    ],
)
def test_title_and_body_never_names_a_person(event):
    club = _club()
    mix_ = _mix()

    title, body = _title_and_body(event, club, mix_)

    assert title == club.name
    # Never a submitter's name, participation mode, or a vote count/result --
    # the only proper nouns allowed are the club name and the mix's own
    # organizer-set theme, both public.
    for leaky_word in ("vote count", "submitted by", "vibing", "playing", "winner"):
        assert leaky_word not in body.lower()


def test_title_and_body_includes_the_club_and_mix_label():
    club = _club(name="Slam Alumni")
    mix_ = _mix(mix_number=7, theme=None)

    _title, body = _title_and_body("voting_open", club, mix_)

    assert "Mystery Mix 7" in body


# --------------------------------------------------------------------------- #
# Recipient gathering (real DB)
# --------------------------------------------------------------------------- #


async def _seed_club_with_member(
    db_session,
    *,
    push_lifecycle=True,
    push_deadline=True,
    removed=False,
    deleted=False,
    device_tokens=1,
):
    organizer = User(email=f"org-{uuid.uuid4()}@example.com", display_name="Org")
    member = User(
        email=f"member-{uuid.uuid4()}@example.com",
        display_name="Member",
        push_lifecycle_enabled=push_lifecycle,
        push_deadline_reminders_enabled=push_deadline,
        deleted_at=datetime.now(timezone.utc) if deleted else None,
    )
    db_session.add_all([organizer, member])
    await db_session.flush()
    club = Club(
        name="Test Club",
        organizer_id=organizer.id,
        total_mixes=3,
        votes_per_player=3,
        state="active",
    )
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    db_session.add(
        ClubMember(
            club_id=club.id,
            user_id=member.id,
            removed_at=datetime.now(timezone.utc) if removed else None,
        )
    )
    for i in range(device_tokens):
        db_session.add(DevicePushToken(user_id=member.id, device_token=f"tok-{member.id}-{i}"))
    await db_session.commit()
    return club, member, organizer


async def test_gather_push_recipients_returns_one_row_per_device(db_session):
    club, member, _organizer = await _seed_club_with_member(db_session, device_tokens=2)

    recipients = await gather_push_recipients(db_session, club.id)

    member_rows = [r for r in recipients if r.user_id == member.id]
    assert len(member_rows) == 2
    assert {r.device_token for r in member_rows} == {f"tok-{member.id}-0", f"tok-{member.id}-1"}


async def test_gather_push_recipients_excludes_lifecycle_disabled(db_session):
    club, member, _organizer = await _seed_club_with_member(db_session, push_lifecycle=False)

    recipients = await gather_push_recipients(db_session, club.id)

    assert member.id not in {r.user_id for r in recipients}


async def test_gather_push_deadline_recipients_excludes_deadline_disabled_but_not_lifecycle(
    db_session,
):
    club, member, _organizer = await _seed_club_with_member(
        db_session, push_lifecycle=True, push_deadline=False
    )

    lifecycle = await gather_push_recipients(db_session, club.id)
    deadline = await gather_push_deadline_recipients(db_session, club.id)

    assert member.id in {r.user_id for r in lifecycle}
    assert member.id not in {r.user_id for r in deadline}


async def test_gather_push_recipients_excludes_removed_member(db_session):
    club, member, _organizer = await _seed_club_with_member(db_session, removed=True)

    recipients = await gather_push_recipients(db_session, club.id)

    assert member.id not in {r.user_id for r in recipients}


async def test_gather_push_recipients_excludes_deleted_account(db_session):
    club, member, _organizer = await _seed_club_with_member(db_session, deleted=True)

    recipients = await gather_push_recipients(db_session, club.id)

    assert member.id not in {r.user_id for r in recipients}


async def test_gather_push_recipients_excludes_member_with_no_device(db_session):
    organizer = User(email=f"org-{uuid.uuid4()}@example.com", display_name="Org")
    member = User(email=f"member-{uuid.uuid4()}@example.com", display_name="Member")
    db_session.add_all([organizer, member])
    await db_session.flush()
    club = Club(name="Test Club", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    db_session.add(ClubMember(club_id=club.id, user_id=member.id))
    await db_session.commit()

    recipients = await gather_push_recipients(db_session, club.id)

    assert member.id not in {r.user_id for r in recipients}


async def test_organizer_push_recipients_excludes_non_organizer_members(db_session):
    club, member, organizer = await _seed_club_with_member(db_session)
    db_session.add(DevicePushToken(user_id=organizer.id, device_token="org-device"))
    await db_session.commit()

    recipients = await organizer_push_recipients(db_session, club)

    assert {r.user_id for r in recipients} == {organizer.id}
    assert member.id not in {r.user_id for r in recipients}


# --------------------------------------------------------------------------- #
# send_push_event: dispatch shape
# --------------------------------------------------------------------------- #


async def test_send_push_event_calls_send_push_once_per_recipient(db_session, monkeypatch):
    from app import config as config_module
    from app.services import push_notifications as push_module

    club, member, _organizer = await _seed_club_with_member(db_session, device_tokens=2)
    mix_ = Mix(id=uuid.uuid4(), club_id=club.id, mix_number=1, theme="test")
    recipients = await gather_push_recipients(db_session, club.id)

    calls = []

    async def fake_send_push(
        client, token_service, bundle_id, device_token, title, body, data=None
    ):
        calls.append(device_token)
        return "ok"

    monkeypatch.setattr(push_module, "send_push", fake_send_push)

    settings = config_module.Settings(_env_file=None)
    await send_push_event(
        _configured_token_service(), settings, recipients, club, mix_, "voting_open"
    )

    assert sorted(calls) == sorted(r.device_token for r in recipients)


async def test_send_push_event_noops_when_unconfigured(db_session, monkeypatch):
    from app import config as config_module
    from app.services import push_notifications as push_module

    club, _member, _organizer = await _seed_club_with_member(db_session)
    mix_ = Mix(id=uuid.uuid4(), club_id=club.id, mix_number=1, theme="test")
    recipients = await gather_push_recipients(db_session, club.id)

    called = {"n": 0}

    async def fake_send_push(*args, **kwargs):
        called["n"] += 1
        return "ok"

    monkeypatch.setattr(push_module, "send_push", fake_send_push)

    settings = config_module.Settings(_env_file=None)
    await send_push_event(
        _unconfigured_token_service(), settings, recipients, club, mix_, "voting_open"
    )

    assert called["n"] == 0


async def test_send_push_event_noops_with_no_recipients(db_session, monkeypatch):
    from app import config as config_module
    from app.services import push_notifications as push_module

    club, _member, _organizer = await _seed_club_with_member(db_session)
    mix_ = Mix(id=uuid.uuid4(), club_id=club.id, mix_number=1, theme="test")

    called = {"n": 0}

    async def fake_send_push(*args, **kwargs):
        called["n"] += 1
        return "ok"

    monkeypatch.setattr(push_module, "send_push", fake_send_push)

    settings = config_module.Settings(_env_file=None)
    await send_push_event(_configured_token_service(), settings, [], club, mix_, "voting_open")

    assert called["n"] == 0


# --------------------------------------------------------------------------- #
# Retire-on-dead-token
# --------------------------------------------------------------------------- #


async def test_retire_deletes_only_the_matching_token(db_session, session_factory, monkeypatch):
    # _retire_device_token opens its own connection via the module-level
    # async_session_factory rather than reusing a caller's session, so the
    # test has to redirect that reference at the module -- same pattern
    # test_advance_mixes.py already established for its own job, which reads
    # the DB the same way. PK captured into a local before any further
    # query, project's own MissingGreenlet-after-expire_all gotcha.
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    member = User(email=f"member-{uuid.uuid4()}@example.com", display_name="Member")
    db_session.add(member)
    await db_session.flush()
    member_id = member.id
    db_session.add(DevicePushToken(user_id=member_id, device_token="dead-token"))
    db_session.add(DevicePushToken(user_id=member_id, device_token="live-token"))
    await db_session.commit()

    await _retire_device_token("dead-token")

    db_session.expire_all()
    remaining = (
        await db_session.scalars(
            select(DevicePushToken).where(DevicePushToken.user_id == member_id)
        )
    ).all()
    assert [t.device_token for t in remaining] == ["live-token"]
