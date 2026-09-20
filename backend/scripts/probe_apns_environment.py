"""Find out, from APNs' own answers, which environment a device's push token is in.

Two questions this settles (MysteryMixClub-4vii.35, ADR 0033):

  * --check-credentials: does APNs accept the configured key, Key ID and Team ID?
    Sends nothing to anyone (a token that belongs to no device). It does not
    validate the topic: APNs checks the device token first.
  * --email <address>: for each device registered to that account, does the
    PRODUCTION gateway accept its token, the SANDBOX gateway, both, or neither?
    A token only the sandbox gateway accepts came from a development-signed
    build, and the backend (production gateway only) can never reach it.

The device probe sends a silent ``background`` push (no alert, no sound; per
Apple's documentation nothing shows on the phone, which has not been observed on
a device here). A 200 is APNs' acceptance, not delivery. Device tokens are read
from the database and used in the request, and are NEVER printed: devices are
identified by position and last-registration time.

Needs the backend's runtime environment (APNs key, DATABASE_URL). On the Droplet,
load it the way the deploy does, then run from backend/:

    sudo -u mysterymixclub bash -c '
      cd /home/mysterymixclub/app/backend &&
      set -a && source /etc/mysterymixclub/staging.env && set +a &&
      .venv/bin/python -m scripts.probe_apns_environment --check-credentials'

(`--email someone@example.com` in place of `--check-credentials` for a device;
prod's env file is /etc/mysterymixclub/prod.env, and prod access is not ad hoc.)

Exit status: 0 = the answer is good for the backend (credentials accepted; every
probed device is a production token), 1 = anything else (sandbox or dead token,
credentials rejected, no clear answer), 2 = nothing to probe or not configured.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from sqlalchemy import func, select

from app.config import get_settings
from app.db.session import async_session_factory
from app.models.device_push_token import DevicePushToken
from app.models.user import User
from app.services.apple_push_token import (
    ApplePushTokenError,
    ApplePushTokenService,
    build_apple_push_token_service,
)
from app.services.apns_probe import (
    CredentialsVerdict,
    EnvironmentVerdict,
    GatewayAnswer,
    check_credentials,
    describe,
    interpret_environment,
    probe_gateways,
)

_ENVIRONMENT_MEANING: dict[EnvironmentVerdict, str] = {
    "production": "PRODUCTION token: the backend's gateway accepts it.",
    "sandbox": (
        "SANDBOX token: only the sandbox gateway accepts it. This build was signed for "
        "development; the backend only uses the production gateway, so it cannot receive "
        "pushes. Install a TestFlight/App Store build (ADR 0033)."
    ),
    "both": "Both gateways accepted it (unexpected).",
    "not_valid_on_either": (
        "Neither gateway knows this token: it is dead, or was not issued for this app."
    ),
    "not_on_production": (
        "The production gateway rejects this token, and this key is not authorized for the "
        "sandbox gateway, so a sandbox token cannot be ruled in or out. The backend cannot "
        "reach it either way."
    ),
    "unregistered": (
        "A gateway knows this token but reports it no longer active (the app was removed or "
        "reinstalled). Not a clean environment answer."
    ),
    "credentials_rejected": (
        "APNs rejected the backend's credentials on the production gateway (403). Fix those first."
    ),
    "inconclusive": "No clear answer (see the statuses above).",
}

_CREDENTIALS_MEANING: dict[CredentialsVerdict, str] = {
    "accepted": (
        "credentials ACCEPTED by the production gateway (a token that belongs to no device was "
        "rejected as expected, which happens only after Apple authenticated the provider)."
    ),
    "rejected": "credentials REJECTED by the production gateway (403).",
    "inconclusive": "no clear answer.",
}


def format_device_line(
    position: int, updated_at: datetime, production: GatewayAnswer, sandbox: GatewayAnswer
) -> str:
    """One line per device. Deliberately takes no token: it cannot leak one."""
    return (
        f"device {position} (last registered {updated_at:%Y-%m-%d %H:%M} UTC): "
        f"production={describe(production)}  sandbox={describe(sandbox)}"
    )


async def _check_credentials(service: ApplePushTokenService, topic: str) -> int:
    credentials, production, sandbox = await check_credentials(service, topic)
    print(f"topic: {topic}")
    print(f"production: {describe(production)}   sandbox: {describe(sandbox)}")
    print(_CREDENTIALS_MEANING[credentials])
    if credentials == "accepted" and sandbox.status_code == 403:
        print(
            "note: this key is not authorized for the sandbox gateway. That is fine: the "
            "backend uses production only."
        )
    return 0 if credentials == "accepted" else 1


async def _probe_devices(service: ApplePushTokenService, topic: str, email: str) -> int:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(DevicePushToken.device_token, DevicePushToken.updated_at)
                .join(User, User.id == DevicePushToken.user_id)
                # Emails are stored lowercased.
                .where(func.lower(User.email) == email.strip().lower())
                .order_by(DevicePushToken.updated_at)
            )
        ).all()
    if not rows:
        print("No devices are registered for that account.")
        return 2
    exit_code = 0
    for position, (device_token, updated_at) in enumerate(rows, start=1):
        production, sandbox = await probe_gateways(service, topic, device_token)
        print(format_device_line(position, updated_at, production, sandbox))
        verdict = interpret_environment(production, sandbox)
        print(f"  -> {_ENVIRONMENT_MEANING[verdict]}")
        if verdict != "production":
            exit_code = 1
    return exit_code


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    service = build_apple_push_token_service(settings)
    if not service.is_configured:
        print("APNs is not configured in this environment (key, Key ID or Team ID missing).")
        return 2
    topic = settings.apple_sign_in_bundle_id
    try:
        if args.check_credentials:
            return await _check_credentials(service, topic)
        return await _probe_devices(service, topic, args.email)
    except ApplePushTokenError:
        print("Could not obtain an APNs provider token (bad key?).")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--check-credentials", action="store_true")
    what.add_argument("--email", help="probe every device registered to this account")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
