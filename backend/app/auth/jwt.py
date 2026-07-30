import uuid
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from jose import JWTError, jwt

from app.config import get_settings

# Re-exported so callers can catch decode failures without importing jose
# directly (jose ships no type stubs; keeping the boundary here confines that).
__all__ = [
    "JWTError",
    "OAuthState",
    "SignInState",
    "GoogleLinkState",
    "create_access_token",
    "decode_access_token",
    "create_oauth_state",
    "decode_oauth_state",
    "create_sign_in_state",
    "decode_sign_in_state",
    "create_google_link_state",
    "decode_google_link_state",
    "create_unsubscribe_token",
    "decode_unsubscribe_token",
]


class OAuthState(NamedTuple):
    """Decoded OAuth-state: the initiating user, plus an optional in-app path to
    return to after the round-trip (e.g. the round that started the connect)."""

    user_id: uuid.UUID
    return_to: str | None


class SignInState(NamedTuple):
    """Decoded sign-in OAuth-state: the anti-CSRF nonce the callback matches
    against the browser's cookie, the invite token (if any) that has to
    survive the round-trip so a brand-new account can still be invite-gated,
    and the PKCE code_verifier (MysteryMixClub-ali8.7) the callback sends back
    to Google alongside the authorization code."""

    nonce: str
    invite_token: str | None
    code_verifier: str


class GoogleLinkState(NamedTuple):
    """Decoded Google-account-link state (MysteryMixClub-ali8.4): which
    already-authenticated user started the link, the anti-CSRF nonce the
    callback matches against the browser's cookie, and the PKCE code_verifier
    (MysteryMixClub-ali8.7) the callback sends back to Google."""

    user_id: uuid.UUID
    nonce: str
    code_verifier: str


# Access tokens are short-lived JWTs (TD 5): 60-minute expiry, HS256, signed
# with the server secret. This module both mints and verifies them.
_ALGORITHM = "HS256"
_ACCESS_TOKEN_TTL = timedelta(minutes=60)
# OAuth-state tokens bind the initiating user to a third-party redirect (MYS-83).
# The callback is an unauthenticated browser redirect, so the user identity rides
# in this signed, short-lived state and is verified on return (anti-CSRF + binding).
_OAUTH_STATE_TTL = timedelta(minutes=10)


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


def create_oauth_state(user_id: uuid.UUID, purpose: str, return_to: str | None = None) -> str:
    """Return a signed, 10-minute state token binding ``user_id`` to ``purpose``
    (e.g. ``"spotify"``) for a third-party OAuth round-trip, optionally carrying a
    ``return_to`` in-app path to land on afterwards. Signing it keeps it
    tamper-proof across the round-trip; callers still validate it on use."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "purpose": purpose,
        "iat": int(now.timestamp()),
        "exp": int((now + _OAUTH_STATE_TTL).timestamp()),
    }
    if return_to:
        claims["rt"] = return_to
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_oauth_state(token: str, purpose: str) -> OAuthState:
    """Verify an OAuth-state token and return its user id + optional return path.

    Raises ``jose.JWTError`` on any failure: malformed, bad signature, expired,
    a missing/invalid ``sub``, or a ``purpose`` that doesn't match (so a state
    minted for one provider can't be replayed against another).
    """
    claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    if claims.get("purpose") != purpose:
        raise JWTError("oauth state purpose mismatch")
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise JWTError("missing or invalid subject claim")
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise JWTError("subject claim is not a valid user id") from exc
    rt = claims.get("rt")
    return OAuthState(user_id=user_id, return_to=rt if isinstance(rt, str) else None)


def create_sign_in_state(nonce: str, code_verifier: str, invite_token: str | None = None) -> str:
    """Return a signed, 10-minute state token for a sign-in OAuth round-trip
    (ADR 0007).

    Unlike :func:`create_oauth_state` this carries no user id — nobody is signed
    in yet, which is the whole point of the flow. Signing keeps the invite token
    from being swapped in transit (it decides whether a brand-new account may be
    created at all), and ``purpose`` stops a state minted here from being
    replayed against the Spotify callback or vice versa.

    Signing alone does NOT prevent login-CSRF — an attacker can start their own
    flow and feed a victim the resulting callback URL. ``nonce`` is what closes
    that: the caller also drops it in a cookie and the callback requires the two
    to match, so the flow can only be finished by the browser that began it.

    ``code_verifier`` is PKCE's code-to-flow binding (MysteryMixClub-ali8.7,
    see :func:`app.services.google_oauth.generate_pkce_pair`) — carried here
    the same way ``invite_token`` is, since the callback needs it back to
    complete the token exchange and this state is the only thing that survives
    the round-trip to Google and back.
    """
    now = datetime.now(timezone.utc)
    claims = {
        "nonce": nonce,
        "cv": code_verifier,
        "purpose": "sign_in",
        "iat": int(now.timestamp()),
        "exp": int((now + _OAUTH_STATE_TTL).timestamp()),
    }
    if invite_token:
        claims["invite"] = invite_token
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_sign_in_state(token: str) -> SignInState:
    """Verify a sign-in state token and return its nonce, code_verifier, and
    optional invite token.

    Raises ``jose.JWTError`` on any failure: malformed, bad signature, expired,
    a ``purpose`` that isn't ``"sign_in"``, or a missing/invalid nonce or
    code_verifier.
    """
    claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    if claims.get("purpose") != "sign_in":
        raise JWTError("sign-in state purpose mismatch")
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise JWTError("missing or invalid nonce claim")
    code_verifier = claims.get("cv")
    if not isinstance(code_verifier, str) or not code_verifier:
        raise JWTError("missing or invalid code_verifier claim")
    invite = claims.get("invite")
    return SignInState(
        nonce=nonce,
        invite_token=invite if isinstance(invite, str) else None,
        code_verifier=code_verifier,
    )


def create_google_link_state(user_id: uuid.UUID, nonce: str, code_verifier: str) -> str:
    """Return a signed, 10-minute state token for linking a Google identity onto
    an already-authenticated account (MysteryMixClub-ali8.4, ADR 0007).

    Distinct from :func:`create_sign_in_state` (which carries no user — nobody's
    signed in yet there) and from :func:`create_oauth_state` (which has no
    nonce). This flow needs the nonce the same way sign-in does: without it, an
    attacker could start their own link flow (binding it to their own account
    via the signed ``sub``), trick a victim into finishing it with the victim's
    Google account, and end up with the victim's Google identity linked onto
    the ATTACKER's account — after which "Sign in with Google" using that
    Google account lands the victim in the attacker's account. The nonce
    closes that: only the browser that started the flow can complete it.

    ``code_verifier`` is PKCE's code-to-flow binding (MysteryMixClub-ali8.7) —
    this flow shares the same underlying code-exchange mechanism as sign-in,
    so it gets the same hardening.
    """
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),
        "nonce": nonce,
        "cv": code_verifier,
        "purpose": "google_link",
        "iat": int(now.timestamp()),
        "exp": int((now + _OAUTH_STATE_TTL).timestamp()),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_google_link_state(token: str) -> GoogleLinkState:
    """Verify a Google-link state token and return its user id, nonce, and
    code_verifier.

    Raises ``jose.JWTError`` on any failure: malformed, bad signature, expired,
    a ``purpose`` that isn't ``"google_link"``, or a missing/invalid ``sub``,
    ``nonce``, or code_verifier.
    """
    claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    if claims.get("purpose") != "google_link":
        raise JWTError("google-link state purpose mismatch")
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise JWTError("missing or invalid subject claim")
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise JWTError("subject claim is not a valid user id") from exc
    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise JWTError("missing or invalid nonce claim")
    code_verifier = claims.get("cv")
    if not isinstance(code_verifier, str) or not code_verifier:
        raise JWTError("missing or invalid code_verifier claim")
    return GoogleLinkState(user_id=user_id, nonce=nonce, code_verifier=code_verifier)


def create_unsubscribe_token(user_id: uuid.UUID) -> str:
    """Return a signed, **non-expiring** token for one-click email unsubscribe.

    Unlike access/state tokens this carries no ``exp``: the link lives in a sent
    email indefinitely and must keep working. It's low-risk — the only action it
    authorizes is turning the recipient's own notification preference off. Signed
    so it can't be forged to unsubscribe someone else; bound to ``purpose`` so it
    can't be swapped with an access/state token."""
    claims = {"sub": str(user_id), "purpose": "unsubscribe"}
    return jwt.encode(claims, get_settings().secret_key, algorithm=_ALGORITHM)


def decode_unsubscribe_token(token: str) -> uuid.UUID:
    """Verify an unsubscribe token and return its ``sub`` as a user id.

    Raises ``jose.JWTError`` on any failure: malformed, bad signature, a
    ``purpose`` that isn't ``"unsubscribe"``, or a missing/invalid ``sub``."""
    claims = jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    if claims.get("purpose") != "unsubscribe":
        raise JWTError("token purpose mismatch")
    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise JWTError("missing or invalid subject claim")
    try:
        return uuid.UUID(sub)
    except ValueError as exc:
        raise JWTError("subject claim is not a valid user id") from exc
