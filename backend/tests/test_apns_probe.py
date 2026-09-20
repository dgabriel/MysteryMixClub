"""Tests for app.services.apns_probe and scripts.probe_apns_environment
(MysteryMixClub-4vii.35).

APNs is stood in for by an httpx.MockTransport that answers per gateway host, so
no network is touched. What matters here: the verdicts follow from the two
answers, the probe is a silent background push, and nothing that identifies a
device or a credential ever reaches the output.
"""

import argparse
import uuid
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.models.device_push_token import DevicePushToken
from app.models.user import User
from app.services.apns_probe import (
    PRODUCTION_HOST,
    SANDBOX_HOST,
    GatewayAnswer,
    check_credentials,
    describe,
    interpret_credentials,
    interpret_environment,
    probe_gateways,
)
from app.services.apple_push_token import ApplePushTokenError, ApplePushTokenService
from scripts import probe_apns_environment as probe_script

_TOPIC = "com.mysterymixclub.app"
_DEVICE_TOKEN = "a1b2c3d4-secret-device-token"
_PRIVATE_KEY = (
    ec.generate_private_key(ec.SECP256R1())
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode()
)

OK = GatewayAnswer(200, None)
BAD_TOKEN = GatewayAnswer(400, "BadDeviceToken")
FORBIDDEN = GatewayAnswer(403, "InvalidProviderToken")


def _service() -> ApplePushTokenService:
    return ApplePushTokenService("TEAM123456", "KEY1234567", _PRIVATE_KEY)


def _apns(answers: dict[str, tuple[int, dict | None]], seen: list[httpx.Request] | None = None):
    """An APNs stand-in answering per gateway host."""

    def dispatch(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        status, body = answers[request.url.host]
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=5.0)


# --------------------------------------------------------------------------- #
# interpret_environment
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("production", "sandbox", "expected"),
    [
        (OK, BAD_TOKEN, "production"),
        (BAD_TOKEN, OK, "sandbox"),
        (OK, OK, "both"),
        (BAD_TOKEN, BAD_TOKEN, "not_valid_on_either"),
        # A production-only key is legitimate: sandbox 403 is a key restriction,
        # not a broken credential, so a live production token still reads as one.
        (OK, FORBIDDEN, "production"),
        (BAD_TOKEN, FORBIDDEN, "not_on_production"),
        # Production 403 means the backend cannot send at all.
        (FORBIDDEN, FORBIDDEN, "credentials_rejected"),
        (FORBIDDEN, OK, "credentials_rejected"),
        (OK, GatewayAnswer(None, None), "production"),
        (GatewayAnswer(410, "Unregistered"), BAD_TOKEN, "unregistered"),
        (BAD_TOKEN, GatewayAnswer(410, "Unregistered"), "unregistered"),
        (GatewayAnswer(None, None), BAD_TOKEN, "inconclusive"),
        (GatewayAnswer(400, "BadTopic"), GatewayAnswer(400, "BadTopic"), "inconclusive"),
        (GatewayAnswer(429, "TooManyRequests"), BAD_TOKEN, "inconclusive"),
    ],
)
def test_interpret_environment(production, sandbox, expected):
    assert interpret_environment(production, sandbox) == expected


@pytest.mark.parametrize(
    ("production", "sandbox", "expected"),
    [
        (BAD_TOKEN, BAD_TOKEN, "accepted"),
        # Judged on the production gateway the backend uses: a production-only
        # key (sandbox 403) is accepted, a rejected production key is not.
        (BAD_TOKEN, FORBIDDEN, "accepted"),
        (FORBIDDEN, BAD_TOKEN, "rejected"),
        (FORBIDDEN, FORBIDDEN, "rejected"),
        (OK, OK, "inconclusive"),  # a fake token can never be accepted: not a clean answer
        (GatewayAnswer(None, None), BAD_TOKEN, "inconclusive"),
        (GatewayAnswer(400, "BadTopic"), BAD_TOKEN, "inconclusive"),
    ],
)
def test_interpret_credentials(production, sandbox, expected):
    assert interpret_credentials(production, sandbox) == expected


def test_describe_is_safe_to_print():
    assert describe(OK) == "200"
    assert describe(BAD_TOKEN) == "400 BadDeviceToken"
    assert describe(GatewayAnswer(None, None)) == "unreachable"


# --------------------------------------------------------------------------- #
# probe_gateways
# --------------------------------------------------------------------------- #


async def test_probe_asks_both_gateways_with_a_silent_background_push():
    seen: list[httpx.Request] = []
    async with _apns(
        {PRODUCTION_HOST: (200, None), SANDBOX_HOST: (400, {"reason": "BadDeviceToken"})}, seen
    ) as client:
        production, sandbox = await probe_gateways(_service(), _TOPIC, _DEVICE_TOKEN, client=client)

    assert (production, sandbox) == (OK, BAD_TOKEN)
    assert [r.url.host for r in seen] == [PRODUCTION_HOST, SANDBOX_HOST]
    for request in seen:
        assert request.headers["apns-push-type"] == "background"
        assert request.headers["apns-priority"] == "5"
        assert request.headers["apns-topic"] == _TOPIC
        assert request.headers["apns-expiration"] == "0"
        # Silent: content-available only, nothing a person would see or hear.
        assert request.content == b'{"aps":{"content-available":1}}'


async def test_a_production_only_key_still_reads_a_live_production_token_as_production():
    async with _apns(
        {
            PRODUCTION_HOST: (200, None),
            SANDBOX_HOST: (403, {"reason": "InvalidProviderToken"}),
        }
    ) as client:
        production, sandbox = await probe_gateways(_service(), _TOPIC, _DEVICE_TOKEN, client=client)

    assert interpret_environment(production, sandbox) == "production"


async def test_probe_survives_an_unreachable_gateway():
    def dispatch(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        production, sandbox = await probe_gateways(_service(), _TOPIC, _DEVICE_TOKEN, client=client)

    assert production == sandbox == GatewayAnswer(None, None)
    assert interpret_environment(production, sandbox) == "inconclusive"


async def test_probe_reads_only_a_plain_word_reason_from_a_hostile_body():
    async with _apns(
        {
            PRODUCTION_HOST: (400, {"reason": "BadTopic\nFAKE LOG LINE"}),
            SANDBOX_HOST: (400, {"reason": "BadDeviceToken"}),
        }
    ) as client:
        production, _ = await probe_gateways(_service(), _TOPIC, _DEVICE_TOKEN, client=client)

    assert production.reason is None  # not a plain word: dropped


async def test_probe_without_credentials_raises_rather_than_sending():
    unconfigured = ApplePushTokenService("", "", "")
    with pytest.raises(ApplePushTokenError):
        await probe_gateways(unconfigured, _TOPIC, _DEVICE_TOKEN)


# --------------------------------------------------------------------------- #
# check_credentials
# --------------------------------------------------------------------------- #


async def test_check_credentials_uses_a_token_that_belongs_to_no_device():
    seen: list[httpx.Request] = []
    async with _apns(
        {
            PRODUCTION_HOST: (400, {"reason": "BadDeviceToken"}),
            SANDBOX_HOST: (400, {"reason": "BadDeviceToken"}),
        },
        seen,
    ) as client:
        verdict, production, sandbox = await check_credentials(_service(), _TOPIC, client=client)

    assert verdict == "accepted"
    assert (production, sandbox) == (BAD_TOKEN, BAD_TOKEN)
    assert all(r.url.path == f"/3/device/{'0' * 64}" for r in seen)


async def test_check_credentials_reports_a_rejected_key():
    async with _apns(
        {
            PRODUCTION_HOST: (403, {"reason": "InvalidProviderToken"}),
            SANDBOX_HOST: (403, {"reason": "InvalidProviderToken"}),
        }
    ) as client:
        verdict, _, _ = await check_credentials(_service(), _TOPIC, client=client)

    assert verdict == "rejected"


# --------------------------------------------------------------------------- #
# scripts.probe_apns_environment: exit codes and what it prints
# --------------------------------------------------------------------------- #

_PROD_TOKEN = "prod-device-token-AAAA"
_SANDBOX_TOKEN = "sandbox-device-token-BBBB"


def _run_args(*, check_credentials: bool = False, email: str = "member@example.com"):
    return argparse.Namespace(check_credentials=check_credentials, email=email)


@pytest.fixture
def configured(monkeypatch):
    """The script with a configured (test) APNs key and no real network."""
    monkeypatch.setattr(
        probe_script, "get_settings", lambda: SimpleNamespace(apple_sign_in_bundle_id=_TOPIC)
    )
    monkeypatch.setattr(probe_script, "build_apple_push_token_service", lambda settings: _service())


def _canned_probe(monkeypatch, answers: dict[str, tuple[GatewayAnswer, GatewayAnswer]]):
    """probe_gateways answering per device token; records nothing about it."""

    async def fake_probe(service, topic, device_token, *, client=None):
        return answers[device_token]

    monkeypatch.setattr(probe_script, "probe_gateways", fake_probe)


async def _seed_devices(db_session, email: str, *tokens: str) -> None:
    user = User(email=email, display_name="Member")
    db_session.add(user)
    await db_session.flush()
    for token in tokens:
        db_session.add(DevicePushToken(user_id=user.id, device_token=token))
    await db_session.commit()


async def test_script_reports_not_configured_and_sends_nothing(monkeypatch, capsys):
    monkeypatch.setattr(
        probe_script, "get_settings", lambda: SimpleNamespace(apple_sign_in_bundle_id=_TOPIC)
    )
    monkeypatch.setattr(
        probe_script, "build_apple_push_token_service", lambda s: ApplePushTokenService("", "", "")
    )

    assert await probe_script._run(_run_args(check_credentials=True)) == 2
    assert "not configured" in capsys.readouterr().out


async def test_script_check_credentials_accepted_exits_zero(configured, monkeypatch, capsys):
    async def fake_check(service, topic, *, client=None):
        return "accepted", BAD_TOKEN, BAD_TOKEN

    monkeypatch.setattr(probe_script, "check_credentials", fake_check)

    assert await probe_script._run(_run_args(check_credentials=True)) == 0
    out = capsys.readouterr().out
    assert "ACCEPTED" in out
    assert _PRIVATE_KEY.splitlines()[1] not in out  # no key material


async def test_script_notes_a_production_only_key_instead_of_calling_it_broken(
    configured, monkeypatch, capsys
):
    async def fake_check(service, topic, *, client=None):
        return "accepted", BAD_TOKEN, FORBIDDEN

    monkeypatch.setattr(probe_script, "check_credentials", fake_check)

    assert await probe_script._run(_run_args(check_credentials=True)) == 0
    assert "not authorized for the sandbox gateway" in capsys.readouterr().out


async def test_script_check_credentials_rejected_exits_one(configured, monkeypatch, capsys):
    async def fake_check(service, topic, *, client=None):
        return "rejected", FORBIDDEN, FORBIDDEN

    monkeypatch.setattr(probe_script, "check_credentials", fake_check)

    assert await probe_script._run(_run_args(check_credentials=True)) == 1
    assert "REJECTED" in capsys.readouterr().out


async def test_script_all_production_devices_exit_zero_and_no_token_is_printed(
    configured, db_session, session_factory, monkeypatch, capsys
):
    monkeypatch.setattr(probe_script, "async_session_factory", session_factory)
    await _seed_devices(db_session, "member@example.com", _PROD_TOKEN)
    _canned_probe(monkeypatch, {_PROD_TOKEN: (OK, BAD_TOKEN)})

    # A mixed-case argument still finds the (lowercased) stored email.
    assert await probe_script._run(_run_args(email="  Member@Example.com ")) == 0

    out = capsys.readouterr().out
    assert "device 1" in out and "PRODUCTION token" in out
    assert _PROD_TOKEN not in out


async def test_script_a_sandbox_device_exits_one_and_says_why(
    configured, db_session, session_factory, monkeypatch, capsys
):
    monkeypatch.setattr(probe_script, "async_session_factory", session_factory)
    await _seed_devices(db_session, "member@example.com", _PROD_TOKEN, _SANDBOX_TOKEN)
    _canned_probe(
        monkeypatch,
        {_PROD_TOKEN: (OK, BAD_TOKEN), _SANDBOX_TOKEN: (BAD_TOKEN, OK)},
    )

    assert await probe_script._run(_run_args()) == 1

    out = capsys.readouterr().out
    assert "device 1" in out and "device 2" in out
    assert "PRODUCTION token" in out and "SANDBOX token" in out
    assert "ADR 0033" in out
    assert _PROD_TOKEN not in out and _SANDBOX_TOKEN not in out


async def test_script_with_no_registered_devices_exits_two(
    configured, db_session, session_factory, monkeypatch, capsys
):
    monkeypatch.setattr(probe_script, "async_session_factory", session_factory)

    assert await probe_script._run(_run_args(email=f"{uuid.uuid4()}@example.com")) == 2
    assert "No devices are registered" in capsys.readouterr().out


async def test_script_a_key_that_cannot_sign_exits_one_without_a_traceback(
    configured, db_session, session_factory, monkeypatch, capsys
):
    monkeypatch.setattr(probe_script, "async_session_factory", session_factory)
    await _seed_devices(db_session, "member@example.com", _PROD_TOKEN)

    async def cannot_sign(service, topic, device_token, *, client=None):
        raise ApplePushTokenError("could not sign apns provider token")

    monkeypatch.setattr(probe_script, "probe_gateways", cannot_sign)

    assert await probe_script._run(_run_args()) == 1
    out = capsys.readouterr().out
    assert "provider token" in out
    assert _PROD_TOKEN not in out
