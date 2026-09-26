"""Unit tests for app.services.apple_push_token (MysteryMixClub-4vii.25).

No network and no real credentials: an ephemeral P-256 keypair is generated per
test so the minted provider token can be verified against the matching public
key. Mirrors test_apple_music_token.py's coverage (minting/claims/header, the
in-process cache, refresh past the deadline, concurrent single-mint,
escaped-newline key normalization, the unconfigured / bad-key error paths, and
the settings-backed factory), minus the exp-related tests -- APNs provider
tokens carry no exp claim.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwt

from app.config import Settings
from app.services.apple_push_token import (
    ApplePushTokenError,
    ApplePushTokenService,
    build_apple_push_token_service,
)

_TEAM_ID = "TEAM123456"
_KEY_ID = "KEY1234567"


def _keypair() -> tuple[str, str]:
    """Return (private PEM, public PEM) for a fresh P-256 (ES256) keypair."""
    key = ec.generate_private_key(ec.SECP256R1())
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _service(private_pem: str, **kwargs) -> ApplePushTokenService:
    return ApplePushTokenService(_TEAM_ID, _KEY_ID, private_pem, **kwargs)


# --------------------------------------------------------------------------- #
# Minting: header, claims, signature
# --------------------------------------------------------------------------- #


async def test_minted_token_verifies_against_public_key_with_correct_header():
    private_pem, public_pem = _keypair()
    service = _service(private_pem)

    token = await service.get_provider_token()

    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["typ"] == "JWT"
    assert header["kid"] == _KEY_ID
    # Decoding with the matching public key both verifies the ES256 signature and
    # returns the claims.
    claims = jwt.decode(token, public_pem, algorithms=["ES256"])
    assert claims["iss"] == _TEAM_ID


async def test_claims_iat_is_now_and_no_exp_claim():
    private_pem, public_pem = _keypair()
    service = _service(private_pem)

    before = int(datetime.now(timezone.utc).timestamp())
    token = await service.get_provider_token()
    after = int(datetime.now(timezone.utc).timestamp())

    claims = jwt.decode(token, public_pem, algorithms=["ES256"])
    assert before <= claims["iat"] <= after
    # APNs documents no exp requirement for provider tokens -- unlike Apple
    # Music's developer token, none is minted.
    assert "exp" not in claims


# --------------------------------------------------------------------------- #
# Caching + refresh
# --------------------------------------------------------------------------- #


async def test_second_call_returns_cached_token_without_reminting():
    private_pem, _ = _keypair()
    service = _service(private_pem)

    first = await service.get_provider_token()
    second = await service.get_provider_token()

    # ES256 signatures are randomized, so an identical string can only come from
    # the cache, not a fresh mint of identical claims.
    assert first == second


async def test_call_inside_refresh_window_mints_fresh_token():
    private_pem, public_pem = _keypair()
    service = _service(private_pem)

    first = await service.get_provider_token()
    # Advance past the refresh deadline while leaving the token cached, so the
    # next call exercises the refresh branch rather than the initial mint.
    service._refresh_after = 0.0
    second = await service.get_provider_token()

    assert second != first
    assert jwt.decode(second, public_pem, algorithms=["ES256"])["iss"] == _TEAM_ID


async def test_reset_cache_forces_remint():
    private_pem, _ = _keypair()
    service = _service(private_pem)

    first = await service.get_provider_token()
    service.reset_cache()
    second = await service.get_provider_token()

    assert second != first


# --------------------------------------------------------------------------- #
# Concurrency
# --------------------------------------------------------------------------- #


async def test_concurrent_callers_share_a_single_mint(monkeypatch):
    private_pem, _ = _keypair()
    service = _service(private_pem)

    calls = {"n": 0}
    original = service._mint

    def counting_mint() -> str:
        calls["n"] += 1
        return original()

    monkeypatch.setattr(service, "_mint", counting_mint)

    results = await asyncio.gather(*(service.get_provider_token() for _ in range(10)))

    assert calls["n"] == 1  # lock + double-check collapses the stampede to one mint
    assert len(set(results)) == 1  # everyone got the same token string


# --------------------------------------------------------------------------- #
# Private-key normalization
# --------------------------------------------------------------------------- #


async def test_escaped_newline_private_key_is_normalized_and_signs():
    private_pem, public_pem = _keypair()
    # Simulate a deploy secret stored single-line with literal "\n" escapes.
    escaped = private_pem.replace("\n", "\\n")
    assert "\n" not in escaped
    service = _service(escaped)

    token = await service.get_provider_token()

    assert jwt.decode(token, public_pem, algorithms=["ES256"])["iss"] == _TEAM_ID


# --------------------------------------------------------------------------- #
# Unconfigured / error paths
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "team_id, key_id, private_key",
    [
        ("", _KEY_ID, "pem"),
        (_TEAM_ID, "", "pem"),
        (_TEAM_ID, _KEY_ID, ""),
        ("", "", ""),
    ],
)
def test_is_configured_requires_all_three(team_id, key_id, private_key):
    service = ApplePushTokenService(team_id, key_id, private_key)
    assert service.is_configured is False


async def test_unconfigured_service_raises_on_get():
    service = ApplePushTokenService("", "", "")
    assert service.is_configured is False
    with pytest.raises(ApplePushTokenError):
        await service.get_provider_token()


async def test_garbage_private_key_raises_apple_push_token_error():
    service = _service("-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n-----END PRIVATE KEY-----")
    # Non-empty, so it reports configured, but signing fails.
    assert service.is_configured is True
    with pytest.raises(ApplePushTokenError) as excinfo:
        await service.get_provider_token()
    # The message is a fixed string with no interpolated (key-adjacent) detail;
    # the underlying JOSE error rides the __cause__ chain instead.
    assert str(excinfo.value) == "could not sign apns provider token"
    assert "not-a-real-key" not in str(excinfo.value)
    assert excinfo.value.__cause__ is not None


# --------------------------------------------------------------------------- #
# Constructor guards
# --------------------------------------------------------------------------- #


def test_ttl_not_greater_than_refresh_margin_raises():
    with pytest.raises(ValueError):
        ApplePushTokenService(
            _TEAM_ID,
            _KEY_ID,
            "pem",
            ttl=timedelta(minutes=10),
            refresh_margin=timedelta(minutes=10),
        )


# --------------------------------------------------------------------------- #
# Settings-backed factory
# --------------------------------------------------------------------------- #


async def test_build_from_settings_reads_team_id_and_push_specific_fields():
    private_pem, public_pem = _keypair()
    settings = Settings(
        apple_music_team_id=_TEAM_ID,
        apple_push_key_id=_KEY_ID,
        apple_push_private_key=private_pem,
        _env_file=None,
    )

    service = build_apple_push_token_service(settings)

    assert service.is_configured is True
    token = await service.get_provider_token()
    header = jwt.get_unverified_header(token)
    assert header["kid"] == _KEY_ID
    assert jwt.decode(token, public_pem, algorithms=["ES256"])["iss"] == _TEAM_ID


def test_build_from_settings_unconfigured_when_key_missing():
    settings = Settings(
        apple_music_team_id=_TEAM_ID,
        apple_push_key_id=_KEY_ID,
        apple_push_private_key="",
        _env_file=None,
    )
    assert build_apple_push_token_service(settings).is_configured is False
