import logging
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
    Response,
    status,
)
from pydantic import EmailStr

from app.api.wire import WireModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.invites import _join_via_invite
from app.auth.jwt import create_access_token
from app.auth.tokens import generate_token, hash_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.club import Club
from app.models.invite import Invite
from app.models.magic_link_token import MagicLinkToken
from app.models.session import Session
from app.models.user import User
from app.services.email import EmailSender, get_email_sender
from app.services.notifications import queue_club_joined

logger = logging.getLogger("app.api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW = timedelta(hours=1)
_TOKEN_TTL = timedelta(minutes=15)

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

_NEUTRAL_MESSAGE = "If that email is registered, a sign-in link is on its way."
_INVALID_LINK_MESSAGE = "invalid or expired link"
_INVALID_SESSION_MESSAGE = "invalid or expired session"
_INVITE_REQUIRED_MESSAGE = "you need an invite to create an account"
_AT_CAPACITY_MESSAGE = "MysteryMixClub is at capacity right now"


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


async def _load_valid_invite(
    db: AsyncSession, invite_token: str | None, now: datetime
) -> Invite | None:
    """Return the invite for ``invite_token`` if it exists, is unexpired, and
    (for a platform invite) hasn't already been used, else None. Legacy
    invites with no expires_at never expire (MYS-126/127). A club invite
    stays multi-use — used_at is never set for one, so that check never
    excludes it. A platform (club-less) invite is single-use (MYS-182
    follow-up): once used_at is stamped, it reads the same as nonexistent."""
    if not invite_token:
        return None
    invite = await db.scalar(select(Invite).where(Invite.token == invite_token))
    if invite is None:
        return None
    if invite.expires_at is not None and invite.expires_at <= now:
        return None
    if invite.club_id is None and invite.used_at is not None:
        return None
    return invite


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
    invite = await _load_valid_invite(db, payload.invite_token, now)
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
    invite_row = await _load_valid_invite(db, invite, now)

    user = await db.scalar(select(User).where(User.email == email, User.deleted_at.is_(None)))
    if user is None:
        # New account: invite-gated sign-up (MYS-127). A valid unexpired invite is
        # required, and creation is blocked once the user cap is reached.
        if invite_row is None:
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE
            )
        total_users = await db.scalar(
            select(func.count()).select_from(User).where(User.deleted_at.is_(None))
        )
        if settings.max_users and (total_users or 0) >= settings.max_users:
            await db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_AT_CAPACITY_MESSAGE)
        if invite_row.club_id is None:
            # Single-use (MYS-182 follow-up): lock and re-check so two
            # concurrent signups can't both consume the same platform invite.
            # A club invite is untouched here — it stays multi-use.
            locked_invite = await db.scalar(
                select(Invite).where(Invite.id == invite_row.id).with_for_update()
            )
            if locked_invite is None or locked_invite.used_at is not None:
                await db.commit()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail=_INVITE_REQUIRED_MESSAGE
                )
        user = User(email=email, display_name="")
        db.add(user)
        await db.flush()
        if invite_row.club_id is None:
            # Stamped together so the preview endpoint can later tell this
            # exact user apart from anyone else hitting the now-dead link.
            assert locked_invite is not None
            locked_invite.used_at = now
            locked_invite.used_by_user_id = user.id

    # Join the invite's club for both new and existing users following a link.
    # Capture user.id into a local before any further async work to avoid the
    # expire_all/MissingGreenlet trap. A platform invite (MYS-182, club_id
    # None) grants signup only — there's no club to join.
    user_id = user.id
    welcome_email: tuple[uuid.UUID, str] | None = None
    if invite_row is not None and invite_row.club_id is not None:
        joined = await _join_via_invite(db, user_id, invite_row)
        if joined:
            club = await db.scalar(select(Club).where(Club.id == invite_row.club_id))
            if club is not None:
                # Capture before commit so ORM expiry can't affect the bg task.
                welcome_email = (club.id, club.name)

    raw_refresh_token = generate_token()
    device_hint = user_agent[:_DEVICE_HINT_MAX_LENGTH] if user_agent else None
    db.add(
        Session(
            user_id=user.id,
            refresh_token_hash=hash_token(raw_refresh_token),
            device_hint=device_hint,
            created_at=now,
            last_used_at=now,
            invalidated_at=None,
        )
    )

    access_token = create_access_token(user.id)

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

    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=raw_refresh_token,
        max_age=_REFRESH_TOKEN_MAX_AGE,
        path=_REFRESH_COOKIE_PATH,
        httponly=True,
        samesite=_REFRESH_COOKIE_SAMESITE,
        secure=settings.secure_cookies,
    )

    return VerifyResponse(access_token=access_token)


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

    # Invalidate every currently-active session for this user only; other users'
    # sessions and already-invalidated rows are untouched (TD 5, security 9).
    await db.execute(
        update(Session)
        .where(
            Session.user_id == session.user_id,
            Session.invalidated_at.is_(None),
        )
        .values(invalidated_at=datetime.now(timezone.utc))
    )
    await db.commit()

    _clear_refresh_cookie(response, settings)
    return LogoutResponse(message="logged out of all devices")
