"""Encryption-at-rest for Spotify refresh tokens (MYS-83).

Spotify's refresh token must be *replayed* to mint new access tokens, so unlike
the app's own session tokens (which we only verify, and therefore hash) it has to
be stored reversibly. We encrypt it with Fernet (AES-128-CBC + HMAC), keyed off
the existing ``SECRET_KEY`` so no new secret is introduced.

``cryptography`` is already a dependency (pulled in by ``python-jose[cryptography]``).
"""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

# Domain-separation label so this derived key can never collide with any other
# use of SECRET_KEY (e.g. JWT signing).
_KDF_LABEL = b"mmc-spotify-refresh-token-v1:"


class SpotifyTokenCryptoError(RuntimeError):
    """Raised when a stored token can't be decrypted (key rotated, corruption)."""


def _derive_fernet_key(secret_key: str) -> bytes:
    """Derive a 32-byte url-safe-base64 Fernet key from ``secret_key``.

    SHA-256 of the labelled secret yields exactly 32 bytes; Fernet wants those
    bytes url-safe-base64 encoded.
    """
    digest = hashlib.sha256(_KDF_LABEL + secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache
def _fernet() -> Fernet:
    secret_key = get_settings().secret_key
    if not secret_key:
        raise SpotifyTokenCryptoError("SECRET_KEY is not configured")
    return Fernet(_derive_fernet_key(secret_key))


def encrypt_refresh_token(token: str) -> str:
    """Encrypt a raw Spotify refresh token for storage. Returns a UTF-8 string."""
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_refresh_token(ciphertext: str) -> str:
    """Decrypt a stored Spotify refresh token.

    Raises :class:`SpotifyTokenCryptoError` if the ciphertext can't be decrypted
    (e.g. SECRET_KEY changed) so callers can prompt the user to reconnect rather
    than crash.
    """
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise SpotifyTokenCryptoError("could not decrypt stored Spotify token") from exc
