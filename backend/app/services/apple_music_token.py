"""Apple Music developer-token service (MYS-105).

Mints and caches the Apple Music *developer token* — an ES256-signed JWT that
identifies the app to Apple's Music API. Server-side only: the MusicKit private
key (``.p8``) is a secret and never leaves the backend.

Unlike the per-user Music User Token (minted client-side via MusicKit JS, then
relayed — see ``docs/discovery/spike-apple-music.md`` §3.2), the developer token
is app-level. Apple caps its lifetime at 180 days; we mint a much shorter-lived
one and refresh it before expiry so a leaked token has a short blast radius.

Like the Spotify/YouTube integrations, Apple config is optional: when the three
``APPLE_MUSIC_*`` values aren't all set the service reports ``is_configured``
False and refuses to mint, so the app degrades gracefully rather than crashing.

``python-jose[cryptography]`` (already a dependency, used by ``app/auth/jwt.py``)
signs ES256 from a PEM private key, so no new dependency is introduced.

References:
  https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens
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
# Apple allows up to 180 days; we keep it short and refresh well before expiry so
# a compromised token is short-lived.
_TOKEN_TTL = timedelta(hours=12)
# Mint a fresh token once less than this remains, avoiding an expiry race.
_REFRESH_MARGIN = timedelta(hours=1)
# Apple rejects developer tokens whose exp is more than 180 days out.
_MAX_TOKEN_TTL = timedelta(days=180)


class AppleMusicTokenError(RuntimeError):
    """Apple Music isn't configured, or the private key couldn't sign a token."""


def _normalize_private_key(private_key: str) -> str:
    """Return the ``.p8`` PEM with real newlines.

    Deploy secrets often carry the multi-line PEM as a single line with literal
    ``\\n`` escapes; turn those back into newlines. A PEM that already has real
    newlines is unaffected. Empty stays empty (treated as unconfigured).
    """
    if not private_key:
        return ""
    return private_key.replace("\\n", "\n").strip()


class AppleMusicTokenService:
    """Mints and in-process-caches the Apple Music developer token.

    Safe under async use: the (rare) mint is guarded by an ``asyncio.Lock`` so
    concurrent callers share one token rather than each signing their own. Hold a
    single instance per process (see :func:`get_apple_music_token_service`);
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
        # re-mint on every call; a ttl over Apple's cap is rejected at request
        # time. Fail loudly at construction rather than storm or 4xx later.
        if ttl <= refresh_margin:
            raise ValueError("ttl must be greater than refresh_margin")
        if ttl > _MAX_TOKEN_TTL:
            raise ValueError("ttl must not exceed apple's 180-day cap")
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

    async def get_developer_token(self) -> str:
        """Return a valid developer token, minting/refreshing as needed.

        Raises :class:`AppleMusicTokenError` if Apple Music is unconfigured, so
        callers can guard on :attr:`is_configured` and skip Apple features rather
        than trigger this.
        """
        if not self.is_configured:
            raise AppleMusicTokenError("apple music credentials are not configured")
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
            "exp": int((now + self._ttl).timestamp()),
        }
        # jose sets ``alg`` and ``typ`` on the header from the algorithm; Apple also
        # requires the signing key's ``kid``.
        headers = {"kid": self._key_id}
        try:
            return jwt.encode(claims, self._private_key, algorithm=_ALGORITHM, headers=headers)
        except JOSEError as exc:
            # No interpolated detail — the underlying error rides the `from exc`
            # chain so nothing key-adjacent lands in a log message.
            raise AppleMusicTokenError("could not sign apple music developer token") from exc


def build_apple_music_token_service(settings: Settings) -> AppleMusicTokenService:
    return AppleMusicTokenService(
        team_id=settings.apple_music_team_id,
        key_id=settings.apple_music_key_id,
        private_key=settings.apple_music_private_key,
    )


@lru_cache
def get_apple_music_token_service() -> AppleMusicTokenService:
    """FastAPI dependency providing the process-wide Apple Music token service.

    Cached so the minted developer token is shared across requests; the instance
    holds its own token cache.
    """
    return build_apple_music_token_service(get_settings())
