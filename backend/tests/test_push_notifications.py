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

import logging
import uuid
from datetime import datetime, timedelta, timezone

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
from app.services import push_notifications as push_module
from app.services.push_notifications import (
    PushRecipient,
    PushResult,
    _dispatch_one,
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


def _reason_client(status_code: int, body: object = None, *, raw: bytes | None = None):
    """An APNs stand-in answering `status_code` with a JSON error body (or raw
    bytes, for malformed-body cases)."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        if raw is not None:
            return httpx.Response(status_code, content=raw)
        return httpx.Response(status_code, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)


class _LogCollector(logging.Handler):
    """Collects the push logger's records. Not ``caplog``: ``app/main.py`` sets
    ``propagate = False`` on the ``app`` logger, so records never reach the
    root logger caplog listens on (same reason test_auth_google.py attaches
    its own handler)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    @property
    def text(self) -> str:
        return "\n".join(self.messages)


@pytest.fixture
def push_logs():
    handler = _LogCollector()
    previous_level = push_module.logger.level
    push_module.logger.setLevel(logging.DEBUG)
    push_module.logger.addHandler(handler)
    try:
        yield handler
    finally:
        push_module.logger.removeHandler(handler)
        push_module.logger.setLevel(previous_level)


@pytest.fixture(autouse=True)
def _reset_accepted_topics():
    """`_accepted_topics` is process-wide state; every test starts unproven."""
    push_module._accepted_topics.clear()
    yield
    push_module._accepted_topics.clear()


async def _send(client: httpx.AsyncClient, device_token: str = "device-token") -> PushResult:
    return await send_push(
        client, _configured_token_service(), _BUNDLE_ID, device_token, "title", "body"
    )


async def _prove_topic() -> None:
    """Have APNs accept the topic once, as a real device's 200 would."""
    async with _client(200) as client:
        assert (await _send(client)).outcome == "ok"


# --------------------------------------------------------------------------- #
# send_push: outcome mapping
# --------------------------------------------------------------------------- #


async def test_send_push_200_is_ok_and_proves_the_topic():
    async with _client(200) as client:
        result = await _send(client)
    assert result == PushResult("ok", 200)
    assert _BUNDLE_ID in push_module._accepted_topics


async def test_send_push_410_unregistered_is_retire_with_apns_timestamp():
    apns_ts_ms = 1_700_000_000_000
    async with _reason_client(410, {"reason": "Unregistered", "timestamp": apns_ts_ms}) as client:
        result = await _send(client)
    assert result.outcome == "retire"
    assert result.status_code == 410
    assert result.reason == "Unregistered"
    assert result.unregistered_at == datetime.fromtimestamp(apns_ts_ms / 1000, tz=timezone.utc)


async def test_send_push_410_without_a_usable_timestamp_still_retires():
    async with _reason_client(410, {"reason": "Unregistered", "timestamp": "soon"}) as client:
        result = await _send(client)
    assert result.outcome == "retire"
    assert result.unregistered_at is None


async def test_send_push_bad_device_token_is_kept_until_the_topic_is_proven(push_logs):
    # APNs answers BadDeviceToken before it ever looks at the topic, and for a
    # token from the other environment too -- alone it proves nothing.
    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        result = await _send(client)
    assert result.outcome == "failed"
    assert result.reason == "BadDeviceToken"
    assert "token is kept" in push_logs.text


async def test_send_push_bad_device_token_retires_once_the_topic_is_proven():
    await _prove_topic()
    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        result = await _send(client)
    assert result.outcome == "retire"
    assert result.reason == "BadDeviceToken"


async def test_send_push_topic_proof_is_per_topic():
    await _prove_topic()  # _BUNDLE_ID accepted; another topic is still unproven
    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        result = await send_push(
            client, _configured_token_service(), "com.example.other", "device-token", "t", "b"
        )
    assert result.outcome == "failed"


@pytest.mark.parametrize(
    "reason",
    ["BadTopic", "TopicDisallowed", "MissingTopic", "PayloadEmpty", "DeviceTokenNotForTopic"],
)
async def test_send_push_unrelated_400_never_retires(reason):
    await _prove_topic()  # even with a proven topic, a request error says nothing about the token
    async with _reason_client(400, {"reason": reason}) as client:
        result = await _send(client)
    assert result.outcome == "failed"
    assert result.status_code == 400
    assert result.reason == reason


@pytest.mark.parametrize(
    ("status_code", "reason"),
    [
        (403, "InvalidProviderToken"),
        (403, "BadCertificateEnvironment"),
        (429, "TooManyRequests"),
        (500, "InternalServerError"),
        (503, "ServiceUnavailable"),
    ],
)
async def test_send_push_provider_and_transient_errors_never_retire(status_code, reason):
    await _prove_topic()
    async with _reason_client(status_code, {"reason": reason}) as client:
        result = await _send(client)
    assert result.outcome == "failed"
    assert result.status_code == status_code
    assert result.reason == reason


@pytest.mark.parametrize(
    ("status_code", "raw"),
    [
        (400, b"<html>bad gateway</html>"),  # not JSON
        (410, b"<html>gone</html>"),  # a 410 with no readable reason is not APNs saying so
        (410, b'{"timestamp": 1700000000000}'),  # JSON, no reason
        (410, b'{"reason": "Gone"}'),  # a 410 reason that is not Unregistered
        (400, b'["BadDeviceToken"]'),  # JSON, not an object
        (400, b'{"reason": {"BadDeviceToken": 1}}'),  # reason of the wrong type
        (400, b'{"reason": "' + b"A" * 2000 + b'"}'),  # oversized body
        (400, b""),  # empty body
    ],
)
async def test_send_push_unreadable_error_body_never_retires(status_code, raw):
    await _prove_topic()
    async with _reason_client(status_code, raw=raw) as client:
        result = await _send(client)
    assert result.outcome == "failed"


async def test_send_push_reason_is_logged_but_never_free_text_or_secrets(push_logs):
    device_token = "a1b2c3d4-secret-device-token"
    hostile = {"reason": "BadTopic\nFAKE LOG LINE authorization: bearer x"}
    async with _reason_client(400, hostile) as client:
        result = await _send(client, device_token)
    assert result.reason is None  # not a plain word, so it is dropped
    assert "FAKE LOG LINE" not in push_logs.text
    assert device_token not in push_logs.text
    assert "unreadable" in push_logs.text


async def test_send_push_logs_status_and_reason_without_token_or_jwt(push_logs):
    device_token = "a1b2c3d4-secret-device-token"
    service = _configured_token_service()
    jwt = await service.get_provider_token()
    async with _reason_client(403, {"reason": "InvalidProviderToken"}) as client:
        await send_push(client, service, _BUNDLE_ID, device_token, "title", "body")
    assert "status=403" in push_logs.text
    assert "InvalidProviderToken" in push_logs.text
    assert device_token not in push_logs.text
    assert jwt not in push_logs.text


async def test_send_push_network_error_is_failed():
    async with _erroring_client() as client:
        result = await _send(client)
    assert result.outcome == "failed"


async def test_send_push_unconfigured_service_is_failed_without_a_request():
    calls = {"n": 0}

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0) as client:
        result = await send_push(
            client, _unconfigured_token_service(), _BUNDLE_ID, "device-token", "title", "body"
        )

    assert result.outcome == "failed"
    assert calls["n"] == 0  # never even tried to reach APNs


async def test_send_push_blank_topic_is_failed_without_a_request(push_logs):
    calls = {"n": 0}

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"reason": "MissingTopic"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0) as client:
        result = await send_push(
            client, _configured_token_service(), "  ", "device-token", "title", "body"
        )

    assert result.outcome == "failed"
    assert calls["n"] == 0
    assert "no apns topic" in push_logs.text


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
        return PushResult("ok")

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
        return PushResult("ok")

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
        return PushResult("ok")

    monkeypatch.setattr(push_module, "send_push", fake_send_push)

    settings = config_module.Settings(_env_file=None)
    await send_push_event(_configured_token_service(), settings, [], club, mix_, "voting_open")

    assert called["n"] == 0


# --------------------------------------------------------------------------- #
# Retire-on-dead-token
# --------------------------------------------------------------------------- #


async def _seed_tokens(db_session, **tokens: str) -> dict[str, uuid.UUID]:
    """One user per keyword, each with the given device token. Returns
    user ids (captured before any expire_all -- the MissingGreenlet trap)."""
    ids: dict[str, uuid.UUID] = {}
    for name, token in tokens.items():
        user = User(email=f"{name}-{uuid.uuid4()}@example.com", display_name=name)
        db_session.add(user)
        await db_session.flush()
        ids[name] = user.id
        db_session.add(DevicePushToken(user_id=user.id, device_token=token))
    await db_session.commit()
    return ids


async def _remaining_tokens(db_session) -> list[str]:
    db_session.expire_all()
    rows = await db_session.scalars(select(DevicePushToken.device_token))
    return sorted(rows.all())


_FAR_FUTURE = datetime.now(timezone.utc) + timedelta(days=1)
_LONG_AGO = datetime.now(timezone.utc) - timedelta(days=1)


async def test_retire_deletes_only_the_matching_token(db_session, session_factory, monkeypatch):
    # _retire_device_token opens its own connection via the module-level
    # async_session_factory rather than reusing a caller's session, so the
    # test has to redirect that reference at the module -- same pattern
    # test_advance_mixes.py already established for its own job, which reads
    # the DB the same way.
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, dead="dead-token", live="live-token")

    retired = await _retire_device_token("dead-token", ids["dead"], not_updated_after=_FAR_FUTURE)

    assert retired is True
    assert await _remaining_tokens(db_session) == ["live-token"]


async def test_retire_protects_a_registration_made_after_the_verdict(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="reregistered-token")

    # The verdict predates this registration, so the device has re-registered
    # since APNs last called the token dead.
    retired = await _retire_device_token(
        "reregistered-token", ids["member"], not_updated_after=_LONG_AGO
    )

    assert retired is False
    assert await _remaining_tokens(db_session) == ["reregistered-token"]


async def test_retire_protects_a_token_handed_to_another_account(
    db_session, session_factory, monkeypatch
):
    # The send went to user A's association; before the verdict landed the
    # phone was signed in as B, so the row now belongs to B and must survive.
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, a="shared-phone-token")
    other = User(email=f"b-{uuid.uuid4()}@example.com", display_name="b")
    db_session.add(other)
    await db_session.flush()
    other_id = other.id
    row = await db_session.scalar(select(DevicePushToken))
    assert row is not None
    row.user_id = other_id
    await db_session.commit()

    retired = await _retire_device_token(
        "shared-phone-token", ids["a"], not_updated_after=_FAR_FUTURE
    )

    assert retired is False
    assert await _remaining_tokens(db_session) == ["shared-phone-token"]


async def _dispatch(recipient: PushRecipient, client: httpx.AsyncClient) -> None:
    await _dispatch_one(
        client, _configured_token_service(), _BUNDLE_ID, recipient, "title", "body", None
    )


async def test_dispatch_retires_on_unregistered_and_logs_without_the_token(
    db_session, session_factory, monkeypatch, push_logs
):
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="dead-device-token-xyz")
    recipient = PushRecipient(ids["member"], "dead-device-token-xyz", "member")
    apns_ts_ms = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000)

    async with _reason_client(410, {"reason": "Unregistered", "timestamp": apns_ts_ms}) as client:
        await _dispatch(recipient, client)

    assert await _remaining_tokens(db_session) == []
    assert "retired a registration apns reports as dead" in push_logs.text
    assert "status=410" in push_logs.text
    assert "dead-device-token-xyz" not in push_logs.text


async def test_dispatch_keeps_a_registration_made_after_the_send_began(
    db_session, session_factory, monkeypatch
):
    # No APNs timestamp to go on (BadDeviceToken carries none): the cutoff falls
    # back to when the send began, so a device that re-registered during the
    # send -- simulated by a registration stamped in the future -- survives.
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="reregistered-mid-send")
    row = await db_session.scalar(select(DevicePushToken))
    assert row is not None
    row.updated_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db_session.commit()
    recipient = PushRecipient(ids["member"], "reregistered-mid-send", "member")
    await _prove_topic()

    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        await _dispatch(recipient, client)

    assert await _remaining_tokens(db_session) == ["reregistered-mid-send"]


async def test_dispatch_never_retires_a_registration_made_after_the_send_even_if_apns_says_later(
    db_session, session_factory, monkeypatch
):
    # A 410 timestamp in the future must not widen the guard past the send.
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="reregistered-mid-send")
    row = await db_session.scalar(select(DevicePushToken))
    assert row is not None
    row.updated_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    await db_session.commit()
    recipient = PushRecipient(ids["member"], "reregistered-mid-send", "member")
    far_future_ms = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)

    async with _reason_client(
        410, {"reason": "Unregistered", "timestamp": far_future_ms}
    ) as client:
        await _dispatch(recipient, client)

    assert await _remaining_tokens(db_session) == ["reregistered-mid-send"]


async def test_dispatch_keeps_a_registration_newer_than_the_apns_timestamp(
    db_session, session_factory, monkeypatch, push_logs
):
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="reregistered-token")
    recipient = PushRecipient(ids["member"], "reregistered-token", "member")
    long_ago_ms = int(_LONG_AGO.timestamp() * 1000)

    async with _reason_client(410, {"reason": "Unregistered", "timestamp": long_ago_ms}) as client:
        await _dispatch(recipient, client)

    assert await _remaining_tokens(db_session) == ["reregistered-token"]
    assert "did not retire" in push_logs.text


@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, {"reason": "BadTopic"}),
        (403, {"reason": "InvalidProviderToken"}),
        (429, {"reason": "TooManyRequests"}),
        (503, {"reason": "ServiceUnavailable"}),
    ],
)
async def test_dispatch_keeps_the_registration_on_provider_and_request_errors(
    db_session, session_factory, monkeypatch, status_code, body
):
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="healthy-token")
    recipient = PushRecipient(ids["member"], "healthy-token", "member")
    await _prove_topic()

    async with _reason_client(status_code, body) as client:
        await _dispatch(recipient, client)

    assert await _remaining_tokens(db_session) == ["healthy-token"]


async def test_dispatch_bad_device_token_only_retires_after_the_topic_is_proven(
    db_session, session_factory, monkeypatch
):
    monkeypatch.setattr("app.services.push_notifications.async_session_factory", session_factory)
    ids = await _seed_tokens(db_session, member="maybe-dead-token")
    recipient = PushRecipient(ids["member"], "maybe-dead-token", "member")

    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        await _dispatch(recipient, client)
    assert await _remaining_tokens(db_session) == ["maybe-dead-token"]  # unproven: kept

    await _prove_topic()
    async with _reason_client(400, {"reason": "BadDeviceToken"}) as client:
        await _dispatch(recipient, client)
    assert await _remaining_tokens(db_session) == []


async def test_unconfigured_apns_with_recipients_is_logged_not_silent(db_session, push_logs):
    from app import config as config_module

    club, _member, _organizer = await _seed_club_with_member(db_session)
    mix_ = Mix(id=uuid.uuid4(), club_id=club.id, mix_number=1, theme="test")
    recipients = await gather_push_recipients(db_session, club.id)
    assert recipients

    settings = config_module.Settings(_env_file=None)
    await send_push_event(
        _unconfigured_token_service(), settings, recipients, club, mix_, "voting_open"
    )

    assert "apns credentials are not configured" in push_logs.text
