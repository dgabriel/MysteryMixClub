import hashlib
import secrets

# Number of random bytes for magic link tokens. token_urlsafe(32) yields a
# 43-character URL-safe string, satisfying the >= 32-byte requirement (TD 5).
_TOKEN_BYTES = 32


def generate_token() -> str:
    """Return a cryptographically random, URL-safe one-time token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a raw token for storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
