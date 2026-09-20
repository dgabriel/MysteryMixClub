"""Which APNs environment does a device token belong to? (MysteryMixClub-4vii.35)

Per Apple's documentation, a device token is only valid on the APNs gateway of
the environment its app was signed for: a build signed with a development
provisioning profile mints *sandbox* tokens, one signed for distribution
(TestFlight, App Store) mints *production* tokens, and a token from the other
environment is answered with ``BadDeviceToken``. The backend only ever talks to
the production gateway (ADR 0033), so a token that only the sandbox gateway
accepts can never receive anything from it. The verdicts below are derived from
the gateways' actual answers, not from that documented mechanism.

Nothing on the server can read a token's environment off the token itself, and
the local archive's entitlements do not say either (a pre-export archive is
signed for development even when the exported build is not). The only real
evidence is APNs' own answer, so this asks both gateways.

The probe is a **silent** ``background`` push (``content-available`` only, no
alert, no sound). Per Apple's documentation that shows nothing on the phone; that
has not been observed on a device here. A 200 from a gateway means that gateway
*accepted* the request for this token -- acceptance, not delivery. That is enough
to tell the environments apart, and nothing else is claimed.

An APNs auth key can be restricted to the sandbox, to production, or both. The
backend only ever uses production, so a 403 from the *sandbox* gateway on its own
means the key is not authorized there, not that the credentials are broken.

No device token, provider JWT or payload is ever returned or logged from here.

https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from app.services.apple_push_token import ApplePushTokenService
from app.services.push_notifications import parse_apns_error

PRODUCTION_HOST = "api.push.apple.com"
SANDBOX_HOST = "api.sandbox.push.apple.com"
# Well-formed but belongs to no device: APNs authenticates the provider first,
# so what it answers to this shows whether the credentials are accepted.
_FAKE_DEVICE_TOKEN = "0" * 64
_TIMEOUT = 10.0


@dataclass(frozen=True)
class GatewayAnswer:
    """One gateway's answer. ``status_code`` is None if it could not be reached;
    ``reason`` is APNs' own reason word (already restricted to letters)."""

    status_code: int | None
    reason: str | None


EnvironmentVerdict = Literal[
    "production",
    "sandbox",
    "both",
    "not_valid_on_either",
    "not_on_production",
    "unregistered",
    "credentials_rejected",
    "inconclusive",
]
CredentialsVerdict = Literal["accepted", "rejected", "inconclusive"]


def _is_bad_device_token(answer: GatewayAnswer) -> bool:
    return answer.status_code == 400 and answer.reason == "BadDeviceToken"


def interpret_environment(production: GatewayAnswer, sandbox: GatewayAnswer) -> EnvironmentVerdict:
    """What the two answers establish about a real device token, judged for the
    backend's purpose: it only uses the production gateway. A 403 from production
    means the backend cannot send at all; a 403 from the sandbox gateway only
    means the key is not authorized there."""
    if production.status_code == 403:
        return "credentials_rejected"
    if production.status_code == 200:
        return "both" if sandbox.status_code == 200 else "production"
    if sandbox.status_code == 200:
        return "sandbox"
    if 410 in (production.status_code, sandbox.status_code) and "Unregistered" in (
        production.reason,
        sandbox.reason,
    ):
        # A gateway knows this token and says it is no longer active (the app
        # was removed or reinstalled): not a clean environment answer.
        return "unregistered"
    if _is_bad_device_token(production):
        if _is_bad_device_token(sandbox):
            # Neither gateway knows this token: it is dead, or was not issued
            # for this app.
            return "not_valid_on_either"
        if sandbox.status_code == 403:
            # Production rejects it, and the key is not authorized to ask the
            # sandbox gateway, so its environment cannot be confirmed there.
            return "not_on_production"
    return "inconclusive"


def interpret_credentials(production: GatewayAnswer, sandbox: GatewayAnswer) -> CredentialsVerdict:
    """What the answers to a *fake* token establish about the credentials, for the
    production gateway the backend uses. ``BadDeviceToken`` for a token that
    cannot exist means APNs got past authenticating the provider (a bad key or
    Team ID is a 403 first); minting a JWT locally proves nothing of the kind.
    The topic is not validated by this: APNs checks the device token first. A
    sandbox 403 alone is a key restriction, not a failure."""
    if production.status_code == 403:
        return "rejected"
    if _is_bad_device_token(production):
        return "accepted"
    return "inconclusive"


async def _ask(
    client: httpx.AsyncClient, host: str, provider_token: str, topic: str, device_token: str
) -> GatewayAnswer:
    try:
        response = await client.post(
            f"https://{host}/3/device/{device_token}",
            json={"aps": {"content-available": 1}},
            headers={
                "authorization": f"bearer {provider_token}",
                "apns-topic": topic,
                "apns-push-type": "background",
                "apns-priority": "5",
                # Deliver now or not at all: nothing should linger on the device.
                "apns-expiration": "0",
            },
        )
    except httpx.HTTPError:
        return GatewayAnswer(None, None)
    reason = None if response.status_code == 200 else parse_apns_error(response)[0]
    return GatewayAnswer(response.status_code, reason)


async def probe_gateways(
    token_service: ApplePushTokenService,
    topic: str,
    device_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[GatewayAnswer, GatewayAnswer]:
    """Ask the production gateway, then the sandbox gateway, about one token.
    Raises ``ApplePushTokenError`` if push is not configured or the key cannot
    sign -- there is nothing to probe with."""
    provider_token = await token_service.get_provider_token()
    owns_client = client is None
    http = client or httpx.AsyncClient(http2=True, timeout=_TIMEOUT)
    try:
        production = await _ask(http, PRODUCTION_HOST, provider_token, topic, device_token)
        sandbox = await _ask(http, SANDBOX_HOST, provider_token, topic, device_token)
    finally:
        if owns_client:
            await http.aclose()
    return production, sandbox


async def check_credentials(
    token_service: ApplePushTokenService,
    topic: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[CredentialsVerdict, GatewayAnswer, GatewayAnswer]:
    """Does APNs accept the configured key, Key ID and Team ID? (Not the topic:
    APNs checks the device token first.) Uses a token that belongs to no device,
    so nothing is ever sent to anyone."""
    production, sandbox = await probe_gateways(
        token_service, topic, _FAKE_DEVICE_TOKEN, client=client
    )
    return interpret_credentials(production, sandbox), production, sandbox


def describe(answer: GatewayAnswer) -> str:
    """``200``, ``400 BadDeviceToken``, ``unreachable`` -- safe to print."""
    if answer.status_code is None:
        return "unreachable"
    return f"{answer.status_code} {answer.reason}" if answer.reason else str(answer.status_code)
