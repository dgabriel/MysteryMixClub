"""APNs provider-authentication token service (MysteryMixClub-4vii.25, IOS-04).

Mints and caches the APNs provider token -- an ES256-signed JWT sent as a
Bearer credential on every push request, proving to Apple's push gateway that
this backend is authorized to send notifications for this app. Structurally
this is `apple_music_token.py` again: same signing library, same PEM
normalization, same in-process cache-with-refresh-margin shape, same
`is_configured` graceful-degradation gate. The two differ only in what claims
go in the JWT and how long a token is trusted -- APNs has no Apple-documented
exp requirement at all (unlike Apple Music's 180-day cap), but Apple's own
guidance is to reuse one token for under an hour rather than mint one per
request, so the same ttl/refresh-margin shape still applies here.

Reuses `Settings.apple_music_team_id` for the Team ID rather than a separate
field: Team ID is account-wide, not specific to the Apple Music key vs. the
APNs key, and this project's iOS bundle id (`apple_sign_in_bundle_id`) is
also already public elsewhere -- only the APNs Key ID and its `.p8` private
key are genuinely new secrets.

``python-jose[cryptography]`` (already a dependency, used by `app/auth/jwt.py`
and `apple_music_token.py`) signs ES256 from a PEM private key, so no new
dependency is introduced.

References:
  https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from jose import jwt
from jose.exceptions import JOSEError

from app.config import Settings, get_settings

_ALGORITHM = "ES256"
# Apple's own guidance: reuse a provider token for under an hour rather than
# mint one per request; a token more than ~1 hour old gets ExpiredProviderToken.
_TOKEN_TTL = timedelta(minutes=50)
# Mint a fresh token once less than this remains, avoiding an expiry race.
_REFRESH_MARGIN = timedelta(minutes=10)


class ApplePushTokenError(RuntimeError):
    """Push notifications aren't configured, or the private key couldn't sign
    a token."""


def _normalize_private_key(private_key: str) -> str:
    """Return the ``.p8`` PEM with real newlines.

    Deploy secrets often carry the multi-line PEM as a single line with literal
    ``\\n`` escapes; turn those back into newlines. A PEM that already has real
    newlines is unaffected. Empty stays empty (treated as unconfigured).
    """
    if not private_key:
        return ""
    return private_key.replace("\\n", "\n").strip()


class ApplePushTokenService:
    """Mints and in-process-caches the APNs provider-authentication token.

    Safe under async use: the (rare) mint is guarded by an ``asyncio.Lock`` so
    concurrent callers share one token rather than each signing their own. Hold
    a single instance per process (see :func:`get_apple_push_token_service`);
    tests can construct their own to isolate the cache.
    """

    def __init__(
        self,
        team_id: str = "",
        key_id: str = "",
        private_key: str = "",
        *,
        ttl: timedelta = _TOKEN_TTL,
        refresh_margin: timedelta = _REFRESH_MARGIN,
    ) -> None:
        # A ttl at/below the margin would floor the refresh deadline to now and
        # re-mint on every call. Fail loudly at construction rather than storm.
        if ttl <= refresh_margin:
            raise ValueError("ttl must be greater than refresh_margin")
        self._team_id = team_id
        self._key_id = key_id
        self._private_key = _normalize_private_key(private_key)
        self._ttl = ttl
        self._refresh_margin = refresh_margin
        self._token: str | None = None
        # Monotonic deadline after which the cached token must be re-minted.
        self._refresh_after: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        """True only when Team ID, Key ID, and the private key are all present."""
        return bool(self._team_id and self._key_id and self._private_key)

    async def get_provider_token(self) -> str:
        """Return a valid APNs provider token, minting/refreshing as needed.

        Raises :class:`ApplePushTokenError` if push isn't configured, so
        callers can guard on :attr:`is_configured` and skip the send rather
        than trigger this.
        """
        if not self.is_configured:
            raise ApplePushTokenError("push notification credentials are not configured")
        if self._token is not None and time.monotonic() < self._refresh_after:
            return self._token
        async with self._lock:
            # Re-check under the lock: another coroutine may have just minted one.
            if self._token is not None and time.monotonic() < self._refresh_after:
                return self._token
            token = self._mint()
            self._token = token
            self._refresh_after = time.monotonic() + max(
                0.0, (self._ttl - self._refresh_margin).total_seconds()
            )
            return token

    def reset_cache(self) -> None:
        """Drop the cached token so the next call re-mints (test/rotation hook)."""
        self._token = None
        self._refresh_after = 0.0

    def _mint(self) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "iss": self._team_id,
            "iat": int(now.timestamp()),
        }
        # jose sets ``alg`` and ``typ`` on the header from the algorithm; APNs also
        # requires the signing key's ``kid``.
        headers = {"kid": self._key_id}
        try:
            return jwt.encode(claims, self._private_key, algorithm=_ALGORITHM, headers=headers)
        except JOSEError as exc:
            # No interpolated detail -- the underlying error rides the `from exc`
            # chain so nothing key-adjacent lands in a log message.
            raise ApplePushTokenError("could not sign apns provider token") from exc


def build_apple_push_token_service(settings: Settings) -> ApplePushTokenService:
    return ApplePushTokenService(
        team_id=settings.apple_music_team_id,
        key_id=settings.apple_push_key_id,
        private_key=settings.apple_push_private_key,
    )


@lru_cache
def get_apple_push_token_service() -> ApplePushTokenService:
    """FastAPI dependency providing the process-wide APNs token service.

    Cached so the minted provider token is shared across requests; the
    instance holds its own token cache.
    """
    return build_apple_push_token_service(get_settings())
