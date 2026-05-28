import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.config import get_settings

# Access tokens are short-lived JWTs (TD 5): 60-minute expiry, HS256, signed
# with the server secret. Decoding/refresh lives in MYS-8; this module only mints.
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
