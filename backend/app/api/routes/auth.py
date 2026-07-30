import asyncio
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import EmailStr, Field

from app.api.wire import WireModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.invites import (
    _active_member_count,
    _CLUB_FULL_MESSAGE,
    _CLUB_MEMBER_CAP,
    _join_via_invite,
)
from app.api.routes.waitlist import _client_ip
from app.auth.jwt import (
    JWTError,
    create_access_token,
    create_sign_in_state,
    decode_google_link_state,
    decode_sign_in_state,
)
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import generate_token, hash_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.club import Club
from app.models.invite import Invite
from app.models.login_attempt import LoginAttempt
from app.models.magic_link_token import MagicLinkToken
from app.models.oauth_callback_attempt import OAuthCallbackAttempt
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.user import User
from app.services.email import EmailSender, get_email_sender
from app.services.google_oauth import (
    GoogleApiError,
    GoogleAuthError,
    GoogleOAuthClient,
    generate_pkce_pair,
    get_google_oauth_client,
)
from app.services.notifications import queue_club_joined

logger = logging.getLogger("app.api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = timedelta(hours=1)
_TOKEN_TTL = timedelta(minutes=15)

# Password reset tokens live longer than a magic link (ADR 0007): the user has
# to choose and confirm a new password after clicking, not just land on a page.
_RESET_TOKEN_TTL = timedelta(minutes=30)
# Brute-force protection for password login. Looser than the magic-link limiter
# (5/hour) because a legitimate user genuinely mistypes a password, and stricter
# in window because an online guessing attack is what this is for. Only FAILED
# attempts are recorded, and a success clears the email's bucket, so an ordinary
# user who eventually gets it right is never locked out.
_LOGIN_ATTEMPT_MAX = 10
_LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
# Length is the only password rule (ADR 0007 sets none). The upper bound caps
# the work an attacker can force argon2 to do per request.
_PASSWORD_MIN_LENGTH = 8
_PASSWORD_MAX_LENGTH = 128

_REFRESH_COOKIE_NAME = "refresh_token"
_REFRESH_COOKIE_PATH = "/api/v1/auth"
# SameSite=Lax (not Strict) so the session survives a return from an external
# OAuth provider (e.g. Spotify connect): Strict withholds the cookie on the
# cross-site-initiated navigation back, which silently logs the user out. Lax is
# safe here — every sensitive endpoint under this path is POST, and Lax still
# withholds the cookie on all cross-site POST/XHR, so it can't be CSRF-forged.
# (Deviates from technical-design §5/§9, which is updated with this rationale.)
# Must match between set and delete or the cookie won't clear.
_REFRESH_COOKIE_SAMESITE: Literal["lax"] = "lax"
# Single source of truth for the 30-day refresh window: the cookie max-age and
# the server-side expiry check both derive from this so they can never drift.
_REFRESH_TOKEN_TTL = timedelta(days=30)
_REFRESH_TOKEN_MAX_AGE = int(_REFRESH_TOKEN_TTL.total_seconds())
_DEVICE_HINT_MAX_LENGTH = 255

# Anti-CSRF nonce for the Google round-trip (ADR 0007). Scoped to the Google
# endpoints, and deliberately SameSite=Lax like the refresh cookie: Strict would
# withhold it on the cross-site navigation back from Google, which is exactly
# when the callback needs to read it.
_GOOGLE_NONCE_COOKIE_NAME = "google_oauth_nonce"
_GOOGLE_NONCE_COOKIE_PATH = "/api/v1/auth/google"
_GOOGLE_NONCE_SAMESITE: Literal["lax"] = "lax"
# Must outlive a slow trip through Google's consent screen without leaving a
# usable nonce lying around; matches the signed state's own 10-minute TTL.
_GOOGLE_NONCE_MAX_AGE = 600
_GOOGLE_UNCONFIGURED_MESSAGE = "google sign-in is not configured on this server"
# Per-IP throttle on the callback itself (MysteryMixClub-ali8.8) — every other
# unauthenticated auth endpoint rate-limits per email, but the callback has no
# email until *after* exchange_code, which is exactly the call being abused.
# Looser than the per-email login limiter (10/15min): an IP can be a shared
# office/NAT address with several legitimate users signing in concurrently,
# not a single identity being brute-forced. The ali8.2 nonce fix already
# limits one /google/login to exactly one usable callback attempt, so this is
# a backstop against sustained abuse, not the primary defense.
_OAUTH_CALLBACK_MAX = 20
_OAUTH_CALLBACK_WINDOW = timedelta(hours=1)

_NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."
_INVALID_LINK_MESSAGE = "invalid or expired link"
_INVALID_SESSION_MESSAGE = "invalid or expired session"
_INVITE_REQUIRED_MESSAGE = "you need an invite to create an account"
_AT_CAPACITY_MESSAGE = "MysteryMixClub is at capacity right now"
# One message for every login failure — wrong password, no password set on the
# account, and unknown email must be indistinguishable (TD 5).
_INVALID_CREDENTIALS_MESSAGE = "invalid email or password"
_TOO_MANY_LOGINS_MESSAGE = "Too many sign-in attempts. Please try again later."
_RESET_NEUTRAL_MESSAGE = "If that email has a password set, a reset link is on its way."
_ACCOUNT_EXISTS_MESSAGE = "an account already exists for this email — sign in instead"

# The invite-gate helpers signal rejection by raising, but the Google callback
# is a top-level navigation — map each rejection to a landing-page flag the
# login screen can render. Keyed on the detail rather than the status code
# because "invite required" and "at capacity" are both 403 but need to say very
# different things. Anything unmapped falls back to a generic "error".
_GOOGLE_SIGNUP_OUTCOMES = {
    _INVITE_REQUIRED_MESSAGE: "invite_required",
    _AT_CAPACITY_MESSAGE: "at_capacity",
    _CLUB_FULL_MESSAGE: "club_full",
}

# Verified against when the email is unknown or the account has no password, so
# a failed login costs the same argon2 work either way. Without this, response
# time alone distinguishes "no such account" from "wrong password" no matter how
# uniform the error body is (TD 5). Hashing a throwaway random value means no
# real password can ever match it.
_DUMMY_PASSWORD_HASH = hash_password(generate_token())


class MagicLinkRequest(WireModel):
    email: EmailStr
    # Shareable invite-link token (MYS-127). A new account can only be created by
    # someone arriving through a valid unexpired link; existing users sign in
    # without one. Carried through to /auth/verify via the magic link's &invite=.
    invite_token: str | None = None


class MagicLinkResponse(WireModel):
    message: str = _NEUTRAL_MESSAGE
    # Dev/staging only: the raw magic-link token, so non-production UIs can show a
    # clickable sign-in link for testing. Omitted entirely in production (the
    # route uses response_model_exclude_none, and it is only set when
    # environment != "production").
    dev_token: str | None = None


class VerifyResponse(WireModel):
    access_token: str
    token_type: str = "bearer"


class LogoutResponse(WireModel):
    message: str


class PasswordLoginRequest(WireModel):
    email: EmailStr
    # No length bounds on login: the rules belong at the point a password is
    # chosen, and rejecting an over/under-length guess here would tell an
    # attacker something about the stored password.
    password: str


class PasswordRegisterRequest(WireModel):
    email: EmailStr
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)
    # Required, unlike the magic-link flow's optional one: password sign-up only
    # ever creates a NEW account, and every new account is invite-gated (MYS-127).
    invite_token: str


class ForgotPasswordRequest(WireModel):
    email: EmailStr


class ForgotPasswordResponse(WireModel):
    message: str = _RESET_NEUTRAL_MESSAGE
    # Dev/staging only, same contract as MagicLinkResponse.dev_token: lets a
    # non-production UI complete a reset without waiting on email. Omitted
    # entirely in production.
    dev_token: str | None = None


class ResetPasswordRequest(WireModel):
    token: str
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)


class ResetPasswordResponse(WireModel):
    message: str


class GoogleEnabledResponse(WireModel):
    enabled: bool


async def _load_valid_invite(
    db: AsyncSession, invite_token: str | None, now: datetime, email: str | None = None
) -> Invite | None:
    """Return the invite for ``invite_token`` if it exists, is unexpired, and
    (for a platform invite) hasn't already been used, else None. Legacy
    invites with no expires_at never expire (MYS-126/127). A club invite
    stays multi-use — used_at is never set for one, so that check never
    excludes it. A platform (club-less) invite is single-use (MYS-182
    follow-up): once used_at is stamped, it reads the same as nonexistent.

    ``email`` is the address the caller is signing in with. A waitlist-issued
    invite (MYS-215) carries a locked email; if it doesn't match, the invite
    reads as nonexistent — same neutral treatment as a bad token, so a
    mismatch can't be distinguished from "no invite" (TD 5). Compared
    case-insensitively here (not just relying on callers to have already
    lowercased both sides) so this can't silently be defeated by a future
    write path that skips normalization."""
    if not invite_token:
        return None
    invite = await db.scalar(select(Invite).where(Invite.token == invite_token))
    if invite is None:
        return None
    if invite.expires_at is not None and invite.expires_at <= now:
        return None
    if invite.club_id is None and invite.used_at is not None:
        return None
    if invite.email is not None and (email is None or invite.email.lower() != email.lower()):
        return None
    return invite


async def _create_invited_user(
    db: AsyncSession,
    email: str,
    invite_row: Invite | None,
    settings: Settings,
    now: datetime,
    password_hash: str | None = None,
) -> User:
    """Create a new account for ``email`` under the invite-gated sign-up rules
    (MYS-127/MYS-182). Shared by magic-link verification and password
    registration; the caller commits on success.

    Commits before raising so work the caller already did — /auth/verify's
    hard-delete of the magic-link token it just consumed — is persisted even
    when sign-up is rejected.
    """
    if invite_row is None:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE)

    total_users = await db.scalar(
        select(func.count()).select_from(User).where(User.deleted_at.is_(None))
    )
    if settings.max_users and (total_users or 0) >= settings.max_users:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_AT_CAPACITY_MESSAGE)

    if invite_row.club_id is not None:
        # MYS-80: block a brand-new account from being created for a club
        # invite that's already full, same spirit as the max_users guard just
        # above — the whole point of this invite was joining that specific
        # club, so there's nothing to sign up for. This is an early exit, not
        # the authoritative check: the race-free one happens inside
        # _join_via_invite once the club row is locked. A signup that slips
        # past this in that narrow race window is allowed to complete rather
        # than unwind an otherwise-finished login (see _join_invite_club).
        if await _active_member_count(db, invite_row.club_id) >= _CLUB_MEMBER_CAP:
            await db.commit()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_CLUB_FULL_MESSAGE)
        user = User(email=email, display_name="", password_hash=password_hash)
        db.add(user)
        await db.flush()
        return user

    # Platform (club-less) invite: single-use (MYS-182 follow-up). Lock and
    # re-check so two concurrent signups can't both consume the same one. A
    # club invite is untouched by this — it stays multi-use.
    locked_invite = await db.scalar(
        select(Invite).where(Invite.id == invite_row.id).with_for_update()
    )
    if locked_invite is None or locked_invite.used_at is not None:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE)

    user = User(email=email, display_name="", password_hash=password_hash)
    db.add(user)
    await db.flush()
    # Stamped together so the preview endpoint can later tell this exact user
    # apart from anyone else hitting the now-dead link.
    locked_invite.used_at = now
    locked_invite.used_by_user_id = user.id
    return user


async def _join_invite_club(
    db: AsyncSession, user_id: uuid.UUID, invite_row: Invite | None
) -> tuple[uuid.UUID, str] | None:
    """Join the invite's club on sign-in/sign-up, returning ``(club_id,
    club_name)`` when a welcome email is owed, else None. A platform invite
    (MYS-182, club_id None) grants signup only — there's no club to join.

    "full" (MYS-80) is deliberately not an error here, unlike the dedicated
    accept-invite endpoint: this is a sign-in flow, and a login must not fail
    just because a club someone has no stake in creating happens to be full. A
    brand-new signup was already turned away in _create_invited_user except for
    the rare race window between that check and this one — in that window it
    completes without the club, same as any other no-op join, rather than
    unwinding an otherwise-finished account creation and login.
    """
    if invite_row is None or invite_row.club_id is None:
        return None
    if await _join_via_invite(db, user_id, invite_row) != "joined":
        return None
    club = await db.scalar(select(Club).where(Club.id == invite_row.club_id))
    if club is None:
        return None
    # Captured before the caller's commit so ORM expiry can't affect the bg task.
    return club.id, club.name


async def _issue_session(
    db: AsyncSession, user_id: uuid.UUID, user_agent: str | None, now: datetime
) -> tuple[str, str]:
    """Start a new session for ``user_id``: add the ``sessions`` row and return
    ``(access_token, raw_refresh_token)``. The caller commits and hands the raw
    refresh token to :func:`_set_refresh_cookie`. Shared by every endpoint that
    logs someone in, so all of them issue sessions identically (TD 5)."""
    raw_refresh_token = generate_token()
    db.add(
        Session(
            user_id=user_id,
            refresh_token_hash=hash_token(raw_refresh_token),
            device_hint=user_agent[:_DEVICE_HINT_MAX_LENGTH] if user_agent else None,
            created_at=now,
            last_used_at=now,
            invalidated_at=None,
        )
    )
    return create_access_token(user_id), raw_refresh_token


def _set_refresh_cookie(response: Response, raw_refresh_token: str, settings: Settings) -> None:
    """Set the refresh cookie. Its attributes must match _clear_refresh_cookie
    exactly or logout won't clear it."""
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=_REFRESH_TOKEN_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        samesite=_REFRESH_COOKIE_SAMESITE,
        secure=settings.secure_cookies,
    )


async def _invalidate_all_sessions(db: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """Invalidate every currently-active session for one user; other users'
    sessions and already-invalidated rows are untouched (TD 5, security 9).
    The caller commits."""
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )


@router.post("/request", response_model=MagicLinkResponse, response_model_exclude_none=True)
async def request_magic_link(
    payload: MagicLinkRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> MagicLinkResponse:
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    recent_count = await db.scalar(
        select(func.count())
        .select_from(MagicLinkToken)
        .where(
            MagicLinkToken.email == email,
            MagicLinkToken.created_at > now - _RATE_LIMIT_WINDOW,
        )
    )
    if (recent_count or 0) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in requests. Please try again later.",
        )

    # Invite-gated sign-up (MYS-127): only send a link to an existing user, or to
    # someone arriving through a valid unexpired invite link. Everyone else gets
    # the SAME neutral response with no token persisted and no mail sent — this is
    # both anti-bot (no open sign-up) and anti-enumeration.
    existing_user = (
        await db.scalar(select(User.id).where(User.email == email, User.deleted_at.is_(None)))
    ) is not None
    invite = await _load_valid_invite(db, payload.invite_token, now, email=email)
    if not existing_user and invite is None:
        logger.debug(
            "Sign-in request without an existing account or valid invite; neutral response"
        )
        return MagicLinkResponse()

    raw_token = generate_token()
    db.add(
        MagicLinkToken(
            email=email,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + _TOKEN_TTL,
            used=False,
        )
    )
    await db.commit()

    link = f"{settings.app_base_url.rstrip('/')}/auth/verify?token={raw_token}"
    # Carry a valid invite token through to verify so the new account (or an
    # existing user following someone's link) is joined to that club.
    if invite is not None:
        link = f"{link}&invite={payload.invite_token}"
    try:
        email_sender.send_magic_link(email, link)
    except Exception:
        # The token is already persisted and valid, so a delivery failure must
        # not take down sign-in. Outside production the dev_token below lets the
        # UI render a clickable link without email. In production email is the
        # only way in, so surface a clean error instead of a raw 500.
        logger.exception("Failed to send magic-link email")
        if settings.environment == "production":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Couldn't send the sign-in email right now. Please try again.",
            )

    response = MagicLinkResponse()
    # Outside production, also hand the token back so dev/staging UIs can render a
    # clickable sign-in link (email isn't always deliverable there). Never in prod.
    if settings.environment != "production":
        response.dev_token = raw_token
    return response


@router.get("/verify", response_model=VerifyResponse)
async def verify_magic_link(
    token: str,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
    user_agent: str | None = Header(default=None),
    invite: str | None = None,
) -> VerifyResponse:
    now = datetime.now(timezone.utc)

    token_row = await db.scalar(
        select(MagicLinkToken).where(MagicLinkToken.token_hash == hash_token(token))
    )

    # Single-use enforcement: any matching token is hard-deleted on lookup,
    # whether it was valid or already expired (TD 5).
    if token_row is not None:
        await db.delete(token_row)

    if token_row is None or token_row.expires_at <= now:
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_LINK_MESSAGE,
        )

    email = token_row.email

    # The invite token (if any) rode here on the link; re-validate it server-side.
    invite_row = await _load_valid_invite(db, invite, now, email=email)

    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        # New account: invite-gated sign-up (MYS-127). Magic-link sign-up never
        # sets a password — that's opt-in later (ADR 0007).
        user = await _create_invited_user(db, email, invite_row, settings, now)

    # Join the invite's club for both new and existing users following a link.
    # Capture user.id into a local before any further async work to avoid the
    # expire_all/MissingGreenlet trap.
    user_id = user.id
    welcome_email = await _join_invite_club(db, user_id, invite_row)

    access_token, raw_refresh_token = await _issue_session(db, user_id, user_agent, now)

    await db.commit()

    if welcome_email is not None:
        queue_club_joined(
            background_tasks,
            email_sender,
            settings,
            email,
            user_id,
            welcome_email[0],
            welcome_email[1],
        )

    _set_refresh_cookie(response, raw_refresh_token, settings)

    return VerifyResponse(access_token=access_token)


@router.post("/login", response_model=VerifyResponse)
async def login_with_password(
    payload: PasswordLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user_agent: str | None = Header(default=None),
) -> VerifyResponse:
    """Sign in with email + password (ADR 0007). Magic link is unaffected; an
    account with no password set simply can't sign in this way."""
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    recent_failures = await db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email,
            LoginAttempt.created_at > now - _LOGIN_ATTEMPT_WINDOW,
        )
    )
    if (recent_failures or 0) >= _LOGIN_ATTEMPT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=_TOO_MANY_LOGINS_MESSAGE,
        )

    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    # Always run a verify, against the dummy hash when there's nothing real to
    # check, so all three failure modes cost the same and are indistinguishable.
    # Off the event loop (argon2 is deliberately expensive and this endpoint is
    # unauthenticated): run inline, it would block every other request on this
    # worker for the duration of each verify.
    stored_hash = user.password_hash if user is not None else None
    password_ok = await asyncio.to_thread(
        verify_password, stored_hash or _DUMMY_PASSWORD_HASH, payload.password
    )
    if user is None or not password_ok:
        db.add(LoginAttempt(email=email, created_at=now))
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_MESSAGE
        )

    user_id = user.id
    # A success clears the bucket, so an ordinary user who mistyped a few times
    # first isn't left one attempt away from a lockout.
    await db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))

    access_token, raw_refresh_token = await _issue_session(db, user_id, user_agent, now)
    await db.commit()

    _set_refresh_cookie(response, raw_refresh_token, settings)
    return VerifyResponse(access_token=access_token)


@router.post("/register", response_model=VerifyResponse, status_code=status.HTTP_201_CREATED)
async def register_with_password(
    payload: PasswordRegisterRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
    user_agent: str | None = Header(default=None),
) -> VerifyResponse:
    """Create a NEW invite-gated account with a password and sign it in
    (ADR 0007).

    This is the password counterpart of the account-creation branch of
    /auth/verify — same invite gate, same user cap, same club join — differing
    only in that email ownership is established by the invite rather than by
    receiving a link, and that ``password_hash`` is set. Adding a password to an
    account that already exists is a separate flow (MysteryMixClub-ali8.4).
    """
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    # Invite first, account lookup second — the order is load-bearing. The 409
    # below necessarily reveals that an account exists, and that disclosure is
    # only acceptable to someone already holding a valid invite for this
    # address (the same trust model the invite link itself runs on). Checking
    # existence first would turn this into an enumeration oracle over the whole
    # users table for anyone with a garbage token, defeating the neutral
    # treatment _load_valid_invite exists to provide. /auth/verify orders these
    # the same way.
    invite_row = await _load_valid_invite(db, payload.invite_token, now, email=email)
    if invite_row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE)

    existing = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ACCOUNT_EXISTS_MESSAGE)

    # Hashed only once the request is known to be worth serving — argon2 is
    # deliberately expensive, so a rejected request must never pay for it.
    # Off the event loop: a synchronous hash would block every other request
    # on this worker for its whole duration (~tens of ms).
    password_hash = await asyncio.to_thread(hash_password, payload.password)
    user = await _create_invited_user(
        db, email, invite_row, settings, now, password_hash=password_hash
    )

    user_id = user.id
    welcome_email = await _join_invite_club(db, user_id, invite_row)

    access_token, raw_refresh_token = await _issue_session(db, user_id, user_agent, now)
    await db.commit()

    if welcome_email is not None:
        queue_club_joined(
            background_tasks,
            email_sender,
            settings,
            email,
            user_id,
            welcome_email[0],
            welcome_email[1],
        )

    _set_refresh_cookie(response, raw_refresh_token, settings)
    return VerifyResponse(access_token=access_token)


@router.post(
    "/forgot-password", response_model=ForgotPasswordResponse, response_model_exclude_none=True
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    email_sender: EmailSender = Depends(get_email_sender),
) -> ForgotPasswordResponse:
    """Email a single-use reset link, if the address has a password to reset.

    Same neutral-response contract as /auth/request: an address with no account,
    or an account that only uses magic link, gets the identical 200 with no token
    persisted and no mail sent (TD 5)."""
    email = payload.email.lower()
    now = datetime.now(timezone.utc)

    recent_count = await db.scalar(
        select(func.count())
        .select_from(PasswordResetToken)
        .where(
            PasswordResetToken.email == email,
            PasswordResetToken.created_at > now - _RATE_LIMIT_WINDOW,
        )
    )
    if (recent_count or 0) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many reset requests. Please try again later.",
        )

    has_password = (
        await db.scalar(
            select(User.id).where(
                User.email == email,
                User.deleted_at.is_(None),
                User.password_hash.is_not(None),
            )
        )
    ) is not None
    if not has_password:
        logger.debug("Password reset requested for an address with no password; neutral response")
        return ForgotPasswordResponse()

    raw_token = generate_token()
    db.add(
        PasswordResetToken(
            email=email,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + _RESET_TOKEN_TTL,
        )
    )
    await db.commit()

    link = f"{settings.app_base_url.rstrip('/')}/auth/reset-password?token={raw_token}"
    try:
        email_sender.send_password_reset(email, link)
    except Exception:
        # The token is already persisted and valid, so a delivery failure must
        # not take down the flow. Outside production the dev_token below still
        # completes it; in production email is the only route, so surface a
        # clean error instead of a raw 500 (mirrors /auth/request).
        logger.exception("Failed to send password-reset email")
        if settings.environment == "production":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Couldn't send the reset email right now. Please try again.",
            )

    resp = ForgotPasswordResponse()
    if settings.environment != "production":
        resp.dev_token = raw_token
    return resp


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> ResetPasswordResponse:
    """Consume a reset token and set a new password.

    Every existing session is invalidated: a reset is the remedy for a
    compromised account, so it has to evict whoever else is signed in. The user
    signs in again with the new password."""
    now = datetime.now(timezone.utc)

    token_row = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(payload.token))
    )
    # Read the email off the row before deleting it, and hard-delete any match
    # whether it was still valid or already expired — that hard delete is what
    # enforces single use (same as magic link, TD 5).
    email = token_row.email if token_row is not None else None
    if token_row is not None:
        await db.delete(token_row)

    if token_row is None or email is None or token_row.expires_at <= now:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_LINK_MESSAGE)

    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        # The account was deleted after the link was mailed. The link is now
        # spent either way; same neutral failure as a bad token.
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_LINK_MESSAGE)

    user.password_hash = await asyncio.to_thread(hash_password, payload.password)
    user_id = user.id
    await _invalidate_all_sessions(db, user_id, now)
    # Clear the brute-force bucket too, so someone locked out by an attacker
    # guessing at their address can still sign in with the password they just set.
    await db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
    await db.commit()

    return ResetPasswordResponse(message="password updated")


# --------------------------------------------------------------------------- #
# Google Sign-In (MysteryMixClub-ali8.2, ADR 0007)
#
# A browser redirect flow, not a JSON API: the callback can't hand back an
# access token in a response body the way /auth/login does, so it sets the
# refresh cookie on a redirect to the SPA, which probes /auth/refresh on mount
# (frontend/src/hooks/useAuth.tsx) and picks the session up from there.
# --------------------------------------------------------------------------- #


def _log_safe(value: str | None, limit: int = 100) -> str:
    """Render an attacker-controlled value safe to log.

    ``repr`` escapes control characters — a raw CRLF in a query param would
    otherwise let the caller forge whole log entries — and the truncation keeps
    an unbounded value from flooding the log.
    """
    return "none" if value is None else repr(value[:limit])


def _google_redirect(settings: Settings, outcome: str) -> RedirectResponse:
    """Bounce back to the SPA with an outcome flag for the login screen.

    Everything after Google's redirect is a top-level browser navigation, so
    failures can't be JSON — they have to be a landing page the user can read.

    Always clears the nonce cookie: it authorizes exactly one callback, and
    every exit from that callback — success or any rejection — consumes it. A
    surviving nonce could satisfy a later flow.
    """
    response = RedirectResponse(
        url=f"{settings.app_base_url.rstrip('/')}/login?google={outcome}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(
        key=_GOOGLE_NONCE_COOKIE_NAME,
        path=_GOOGLE_NONCE_COOKIE_PATH,
        httponly=True,
        samesite=_GOOGLE_NONCE_SAMESITE,
        secure=settings.secure_cookies,
    )
    return response


def _google_link_redirect(settings: Settings, outcome: str) -> RedirectResponse:
    """Bounce back to account settings with an outcome flag
    (MysteryMixClub-ali8.4) -- the account-link counterpart of
    :func:`_google_redirect`. Lands on ``/profile`` instead of ``/login``: the
    caller is already authenticated and isn't switching identity, just adding
    one, so there's no reason to send them through the login screen.

    Same cookie-clearing contract as :func:`_google_redirect` (shared cookie
    name/path -- only one Google round-trip is ever in flight per browser).
    """
    response = RedirectResponse(
        url=f"{settings.app_base_url.rstrip('/')}/profile?google_link={outcome}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    response.delete_cookie(
        key=_GOOGLE_NONCE_COOKIE_NAME,
        path=_GOOGLE_NONCE_COOKIE_PATH,
        httponly=True,
        samesite=_GOOGLE_NONCE_SAMESITE,
        secure=settings.secure_cookies,
    )
    return response


@router.get("/google/enabled", response_model=GoogleEnabledResponse)
async def google_enabled(
    client: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> GoogleEnabledResponse:
    """Whether the frontend should render the Google sign-in button at all —
    checked on page load rather than only at click time, so a disabled Google
    integration never shows a button that would just 404.

    Exposes only the same ``is_configured`` boolean that already gates
    /google/login's own 404; no credential ever reaches the client.
    """
    return GoogleEnabledResponse(enabled=client.is_configured)


@router.get("/google/login")
async def google_login(
    invite_token: str | None = None,
    settings: Settings = Depends(get_settings),
    client: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> RedirectResponse:
    """Redirect to Google's consent screen.

    404 when Google isn't configured, matching the "hidden when unconfigured"
    behavior the staging runbook documents — an unconfigured deployment is a
    normal state, not an error.

    ``invite_token`` rides through the round-trip inside the signed state so a
    brand-new account can still be invite-gated on the way back (ADR 0007: every
    new signup goes through the invite gate, whichever method it uses).

    Also carries a PKCE challenge (MysteryMixClub-ali8.7) so the code
    exchange can only be completed by whoever holds the matching verifier,
    which never leaves the server.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_GOOGLE_UNCONFIGURED_MESSAGE
        )

    nonce = generate_token()
    code_verifier, code_challenge = generate_pkce_pair()
    response = RedirectResponse(
        url=client.authorize_url(
            create_sign_in_state(nonce, code_verifier, invite_token), code_challenge
        ),
        status_code=status.HTTP_302_FOUND,
    )
    # The nonce's other half. The callback requires this cookie to match the
    # nonce inside the signed state, so a flow started in an attacker's browser
    # can't be completed in the victim's (login-CSRF).
    response.set_cookie(
        key=_GOOGLE_NONCE_COOKIE_NAME,
        value=nonce,
        max_age=_GOOGLE_NONCE_MAX_AGE,
        path=_GOOGLE_NONCE_COOKIE_PATH,
        httponly=True,
        samesite=_GOOGLE_NONCE_SAMESITE,
        secure=settings.secure_cookies,
    )
    return response


@router.get("/google/callback")
async def google_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    client: GoogleOAuthClient = Depends(get_google_oauth_client),
    email_sender: EmailSender = Depends(get_email_sender),
    user_agent: str | None = Header(default=None),
    google_oauth_nonce: str | None = Cookie(default=None, alias=_GOOGLE_NONCE_COOKIE_NAME),
) -> RedirectResponse:
    """Google redirects here after consent -- for BOTH the sign-in flow
    (MysteryMixClub-ali8.2) and the authenticated account-link flow
    (MysteryMixClub-ali8.4). One endpoint, not two: registering a second
    redirect URI with Google is a real OAuth-console + per-environment-secret
    change for what's otherwise the exact same code-exchange mechanism, so the
    two flows are told apart by which state type ``state`` decodes as instead.

    Validates state against the browser's nonce cookie, exchanges the code,
    then either resolves/creates an account and signs in (sign-in state) or
    links the identity onto the already-authenticated account that started the
    flow (link state, MysteryMixClub-ali8.4) -- the link path issues no new
    session; the caller's existing one is untouched.

    Per-IP rate limited (MysteryMixClub-ali8.8) before any of that: a hit
    here can't be attributed to an email/identity yet (that's the whole
    reason the callback is a target), so this throttles by client IP instead.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_GOOGLE_UNCONFIGURED_MESSAGE
        )

    ip = _client_ip(request)
    rate_limit_now = datetime.now(timezone.utc)
    recent_attempts = await db.scalar(
        select(func.count())
        .select_from(OAuthCallbackAttempt)
        .where(
            OAuthCallbackAttempt.ip == ip,
            OAuthCallbackAttempt.created_at > rate_limit_now - _OAUTH_CALLBACK_WINDOW,
        )
    )
    if (recent_attempts or 0) >= _OAUTH_CALLBACK_MAX:
        logger.warning("google callback: rate limit exceeded for ip %s", _log_safe(ip))
        return _google_redirect(settings, "rate_limited")
    db.add(OAuthCallbackAttempt(ip=ip, created_at=rate_limit_now))
    await db.commit()

    sign_in_state = None
    link_state = None
    if state:
        try:
            sign_in_state = decode_sign_in_state(state)
        except JWTError:
            try:
                link_state = decode_google_link_state(state)
            except JWTError:
                pass  # neither decode worked; handled by the invalid_state check below

    def _redirect(outcome: str) -> RedirectResponse:
        if link_state is not None:
            return _google_link_redirect(settings, outcome)
        return _google_redirect(settings, outcome)

    if error or not code or not state:
        logger.info("google callback: denied or missing code/state (error=%s)", _log_safe(error))
        return _redirect("denied")

    if sign_in_state is None and link_state is None:
        logger.warning("google callback: state failed verification")
        return _redirect("invalid_state")

    nonce = sign_in_state.nonce if sign_in_state is not None else link_state.nonce  # type: ignore[union-attr]
    # Constant-time compare: the nonce is a secret the attacker is trying to
    # guess. The cookie is fully attacker-controlled, and compare_digest raises
    # TypeError on a non-ASCII str, so a non-ASCII value has to be rejected as
    # simply not matching rather than allowed to become a 500.
    if (
        google_oauth_nonce is None
        or not google_oauth_nonce.isascii()
        or not secrets.compare_digest(google_oauth_nonce, nonce)
    ):
        logger.warning("google callback: state nonce did not match the browser cookie")
        return _redirect("invalid_state")

    # PKCE (MysteryMixClub-ali8.7): sent back to Google alongside the code so
    # it can verify this exchange is completing the same flow that requested
    # the code, not a replay from a separately-leaked code.
    code_verifier = (
        sign_in_state.code_verifier if sign_in_state is not None else link_state.code_verifier  # type: ignore[union-attr]
    )
    try:
        access_token = await client.exchange_code(code, code_verifier)
        identity = await client.fetch_identity(access_token)
    except (GoogleAuthError, GoogleApiError):
        logger.exception("google callback: code exchange or userinfo lookup failed")
        return _redirect("exchange_failed")

    if not identity.email_verified:
        # An unverified Google address proves nothing about who owns that
        # mailbox, so it must never match, create, or link an account here.
        logger.warning("google callback: refusing an unverified google email")
        return _redirect("email_unverified")

    if link_state is not None:
        outcome = await _link_google_identity(db, link_state.user_id, identity.subject)
        await db.commit()
        return _redirect(outcome)

    # link_state was None past the check above, and the earlier "neither
    # decoded" check already ruled out both being None -- so sign_in_state is
    # guaranteed set here. Asserted for mypy and as a runtime guard.
    assert sign_in_state is not None
    now = datetime.now(timezone.utc)
    email = identity.email.lower()

    try:
        user, welcome_email = await _resolve_google_account(
            db, identity.subject, email, sign_in_state.invite_token, settings, now
        )
    except HTTPException as exc:
        # The shared invite-gate helpers raise HTTP errors, but this is a
        # top-level navigation — translate to a landing the user can read.
        logger.info("google callback: sign-up rejected (%s)", exc.detail)
        return _redirect(_GOOGLE_SIGNUP_OUTCOMES.get(exc.detail, "error"))

    user_id = user.id
    # The access token is deliberately discarded rather than put in the redirect
    # URL: a query string lands in browser history, referrers, and server logs.
    # The SPA's on-mount /auth/refresh turns the cookie into one immediately.
    _, raw_refresh_token = await _issue_session(db, user_id, user_agent, now)
    await db.commit()

    if welcome_email is not None:
        queue_club_joined(
            background_tasks,
            email_sender,
            settings,
            email,
            user_id,
            welcome_email[0],
            welcome_email[1],
        )

    response = _redirect("ok")
    _set_refresh_cookie(response, raw_refresh_token, settings)
    return response


async def _resolve_google_account(
    db: AsyncSession,
    google_subject: str,
    email: str,
    invite_token: str | None,
    settings: Settings,
    now: datetime,
) -> tuple[User, tuple[uuid.UUID, str] | None]:
    """Map a verified Google identity to an account, creating one if needed.

    Three cases, in order:

    1. **Already linked** — a user carries this ``google_id``. Straight sign-in.
    2. **Same verified email** — link ``google_id`` onto that account and sign
       in. Deliberately NOT invite-gated: the account already exists, and
       Google has just proven ownership of its address more strongly than
       anything else in this system does. If the account was already linked to
       a *different* Google identity, the new one wins: whoever currently
       controls the verified address is the rightful owner, and leaving the
       stale link would lock them out of their own account.
    3. **Nobody** — a brand-new account, which IS invite-gated exactly like
       magic-link and password sign-up (ADR 0007).

    Returns the user plus any club-welcome email the caller should queue.
    """
    user = await db.scalar(
        select(User).where(User.google_id == google_subject, User.deleted_at.is_(None))
    )
    if user is not None:
        return user, None

    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is not None:
        if user.google_id is not None and user.google_id != google_subject:
            # Replacing a live link, not filling in a blank one. Google won't
            # verify one address on two accounts, so reaching this at all is
            # notable — log it, because to a user later reviewing their linked
            # identities a silent swap is indistinguishable from a hijack.
            logger.warning(
                "google callback: relinking user %s from google_id %s to %s",
                user.id,
                user.google_id,
                google_subject,
            )
        user.google_id = google_subject
        return user, None

    invite_row = await _load_valid_invite(db, invite_token, now, email=email)
    user = await _create_invited_user(db, email, invite_row, settings, now)
    user.google_id = google_subject
    # Capture the PK before further async work (project MissingGreenlet gotcha).
    user_id = user.id
    welcome_email = await _join_invite_club(db, user_id, invite_row)
    return user, welcome_email


async def _link_google_identity(db: AsyncSession, user_id: uuid.UUID, google_subject: str) -> str:
    """Link ``google_subject`` onto ``user_id``'s account (MysteryMixClub-ali8.4).

    Returns an outcome flag for the settings-page redirect:

    - ``"linked"`` — success.
    - ``"already_linked_elsewhere"`` — the identity belongs to a *different*
      account. Google won't verify one address for two accounts, but two
      different Google accounts can still collide with our side by
      coincidence, so this is a real, reachable case, not defensive-only.
    - ``"error"`` — the account was deleted mid-flow.
    """
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        return "error"

    conflicting_owner = await db.scalar(
        select(User.id).where(User.google_id == google_subject, User.id != user_id)
    )
    if conflicting_owner is not None:
        return "already_linked_elsewhere"

    if user.google_id is not None and user.google_id != google_subject:
        # Replacing a live link, not filling in a blank one -- same
        # notable-enough-to-log case _resolve_google_account treats this way.
        logger.warning(
            "google link: relinking user %s from google_id %s to %s",
            user_id,
            user.google_id,
            google_subject,
        )
    user.google_id = google_subject
    return "linked"


@router.post("/refresh", response_model=VerifyResponse)
async def refresh_access_token(
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> VerifyResponse:
    now = datetime.now(timezone.utc)

    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION_MESSAGE,
        )

    session = await db.scalar(
        select(Session).where(Session.refresh_token_hash == hash_token(refresh_token))
    )

    # Neutral 401 for any failure mode (no session / logged out / expired) so the
    # caller can't distinguish the reasons (TD 5). Expiry derives from created_at
    # since the sessions table has no expires_at column.
    if (
        session is None
        or session.invalidated_at is not None
        or session.created_at <= now - _REFRESH_TOKEN_TTL
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION_MESSAGE,
        )

    session.last_used_at = now
    access_token = create_access_token(session.user_id)
    await db.commit()

    return VerifyResponse(access_token=access_token)


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Clear the refresh cookie, matching the name, path, and security
    attributes used when it was set in /auth/verify. A cookie only clears when
    its name and path match the original."""
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        samesite=_REFRESH_COOKIE_SAMESITE,
        secure=settings.secure_cookies,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    # Logout is idempotent: always clear the cookie and return 200, whether the
    # cookie is missing, unmatched, or already invalidated (TD 5). Only an
    # active session for the presented token is invalidated.
    if refresh_token is not None:
        session = await db.scalar(
            select(Session).where(Session.refresh_token_hash == hash_token(refresh_token))
        )
        if session is not None and session.invalidated_at is None:
            session.invalidated_at = datetime.now(timezone.utc)
            await db.commit()

    _clear_refresh_cookie(response, settings)
    return LogoutResponse(message="logged out")


@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LogoutResponse:
    # The presenting session identifies the user regardless of its own
    # invalidated_at state, so an already-invalidated cookie can still log out
    # the user's other devices. No identifiable session => 401 (no user to act
    # on), using the same neutral detail as /auth/refresh (TD 5).
    session = (
        await db.scalar(
            select(Session).where(Session.refresh_token_hash == hash_token(refresh_token))
        )
        if refresh_token is not None
        else None
    )
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_SESSION_MESSAGE,
        )

    await _invalidate_all_sessions(db, session.user_id, datetime.now(timezone.utc))
    await db.commit()

    _clear_refresh_cookie(response, settings)
    return LogoutResponse(message="logged out of all devices")
