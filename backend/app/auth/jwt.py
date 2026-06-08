import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings

# Re-exported so callers can catch decode failures without importing jose
# directly (jose ships no type stubs; keeping the boundary here confines that).
__all__ = ["JWTError", "create_access_token", "decode_access_token"]

# Access tokens are short-lived JWTs (TD 5): 60-minute expiry, HS256, signed
# with the server secret. This module both mints and verifies them.
_ALGORITHM = "HS256"
_ACCESS_TOKEN_TTL = timedelta(minutes=60)


def create_access_token(user_id: uuid.UUID) -> str:
    """Return a signed 60-minute JWT access token for the given user."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + _ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Verify an access token and return its ``sub`` claim as a user id.

    Raises ``jose.JWTError`` (which includes ``ExpiredSignatureError``) on any
    failure: malformed token, bad signature, expired, or a missing/invalid
    ``sub`` claim. Callers catch the single base type.
    """
    claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise JWTError("missing or invalid subject claim")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise JWTError("subject claim is not a valid user id") from exc
