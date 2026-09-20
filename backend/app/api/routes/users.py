import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import Field, StringConstraints, model_validator

from app.api.wire import WireModel
from sqlalchemy import delete, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import (
    _GOOGLE_NONCE_COOKIE_NAME,
    _GOOGLE_NONCE_COOKIE_PATH,
    _GOOGLE_NONCE_MAX_AGE,
    _GOOGLE_NONCE_SAMESITE,
    _GOOGLE_UNCONFIGURED_MESSAGE,
    _PASSWORD_MAX_LENGTH,
    _PASSWORD_MIN_LENGTH,
    session_is_live,
)
from app.api.routes.mixes import ResultNote, ResultVoter
from app.auth.deps import get_current_session_id, get_current_user
from app.auth.jwt import create_google_link_state
from app.auth.passwords import hash_password
from app.auth.tokens import generate_token
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.club import Club
from app.models.auth_identity import AuthIdentity
from app.models.club_member import ClubMember
from app.models.device_push_token import DevicePushToken
from app.models.login_attempt import LoginAttempt
from app.models.mix import Mix
from app.models.note import Note
from app.models.password_reset_token import PasswordResetToken
from app.models.session import Session
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.services.google_oauth import GoogleOAuthClient, generate_pkce_pair, get_google_oauth_client
from app.services.source_tracks import source_fields

router = APIRouter(prefix="/users", tags=["users"])

# Allowed streaming services per the data model (TD 6).
PreferredService = Literal["spotify", "youtube", "deezer"]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class UserProfileResponse(WireModel):
    id: str
    display_name: str
    email: str
    preferred_service: str | None
    email_notifications: bool
    # Whether this account may use the platform-admin tools (MYS-128). Derived
    # from SEED_ADMIN_EMAILS so the UI can gate the /admin nav entry.
    is_platform_admin: bool
    # Whether the user has accepted the current Terms of Service / Privacy
    # Policy (MYS-183). Drives the frontend's consent gate.
    tos_accepted: bool
    # Whether a password/Google identity is already set (MysteryMixClub-ali8.6)
    # -- never the credential itself, just presence. Drives account settings:
    # show "set password" only when there isn't one yet (POST /users/me/password
    # 409s otherwise), and "linked" vs "link google" accordingly.
    has_password: bool
    google_linked: bool
    apple_linked: bool
    # Push equivalents of email_notifications, independent of it and of each
    # other (MysteryMixClub-4vii.25, IOS-04). Present regardless of whether
    # the account has any registered device -- these are the preference, not
    # "can this account currently receive a push."
    push_lifecycle_enabled: bool
    push_deadline_reminders_enabled: bool


class UserProfileUpdate(WireModel):
    # All fields optional: only those explicitly provided are applied. email is
    # intentionally not updatable.
    display_name: DisplayName | None = None
    preferred_service: PreferredService | None = None
    email_notifications: bool | None = None
    push_lifecycle_enabled: bool | None = None
    push_deadline_reminders_enabled: bool | None = None
    # Accepting the Terms of Service / Privacy Policy (MYS-183). Only `true` is
    # a meaningful value — there's no client-initiated "unaccept" — so this is
    # the sole literal accepted; the server stamps its own timestamp below,
    # never trusting one from the client.
    accept_terms: Literal[True] | None = None

    # These map to NOT NULL columns: allow omission (partial update) but
    # reject an explicit null (422).
    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_null(cls, data):
        if isinstance(data, dict):
            for field in (
                "display_name",
                "email_notifications",
                "push_lifecycle_enabled",
                "push_deadline_reminders_enabled",
            ):
                if field in data and data[field] is None:
                    raise ValueError(f"{field} may not be null")
        return data


class ExportSubmission(WireModel):
    id: str
    round_id: str
    # None for a source-only track, identified by source_key instead (MYS-201).
    isrc: str | None
    source_key: str | None
    title: str
    artist: str
    album: str | None
    note: str | None
    participation_mode: str
    created_at: datetime


class ExportVote(WireModel):
    id: str
    round_id: str
    submission_id: str
    # How many votes the person put on this song (ADR 0014). Exported because a
    # weighted vote is a different fact about them than a plain one.
    weight: int
    created_at: datetime


class ExportNote(WireModel):
    id: str
    round_id: str
    submission_id: str
    body: str
    created_at: datetime


class ExportClubMembership(WireModel):
    league_id: str
    league_name: str
    role: str
    joined_at: datetime


class UserDataExportResponse(WireModel):
    exported_at: datetime
    profile: UserProfileResponse
    submissions: list[ExportSubmission]
    votes: list[ExportVote]
    notes: list[ExportNote]
    club_memberships: list[ExportClubMembership]


async def _to_profile(user: User, settings: Settings, db: AsyncSession) -> UserProfileResponse:
    apple_linked = (
        await db.scalar(
            select(AuthIdentity.id).where(
                AuthIdentity.user_id == user.id, AuthIdentity.provider == "apple"
            )
        )
        is not None
    )
    return UserProfileResponse(
        id=str(user.id),
        display_name=user.display_name,
        email=user.email,
        preferred_service=user.preferred_service,
        email_notifications=user.email_notifications,
        is_platform_admin=user.email.lower() in settings.seed_admin_email_set,
        tos_accepted=user.tos_accepted_at is not None,
        has_password=user.password_hash is not None,
        google_linked=user.google_id is not None,
        apple_linked=apple_linked,
        push_lifecycle_enabled=user.push_lifecycle_enabled,
        push_deadline_reminders_enabled=user.push_deadline_reminders_enabled,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserProfileResponse:
    return await _to_profile(current_user, settings, db)


@router.get("/me/export", response_model=UserDataExportResponse)
async def export_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserDataExportResponse:
    """Right of access / data portability (GDPR Art. 15/20, MYS-185).

    Returns a JSON dump of everything tied to the caller's own account: profile,
    submissions, votes, notes, and club memberships. Read-only — mirrors the
    same tables the hard-purge cascade touches (app.jobs.purge_accounts) but
    selects rather than deletes.
    """
    submissions = await db.scalars(select(Submission).where(Submission.user_id == current_user.id))
    votes = await db.scalars(select(Vote).where(Vote.voter_id == current_user.id))
    notes = await db.scalars(select(Note).where(Note.author_id == current_user.id))
    memberships = await db.execute(
        select(ClubMember, Club.name)
        .join(Club, Club.id == ClubMember.club_id)
        .where(ClubMember.user_id == current_user.id)
    )

    return UserDataExportResponse(
        exported_at=datetime.now(timezone.utc),
        profile=await _to_profile(current_user, settings, db),
        submissions=[
            ExportSubmission(
                id=str(s.id),
                round_id=str(s.mix_id),
                isrc=s.isrc,
                source_key=s.source_key,
                title=s.title,
                artist=s.artist,
                album=s.album,
                note=s.note,
                participation_mode=s.participation_mode,
                created_at=s.created_at,
            )
            for s in submissions
        ],
        votes=[
            ExportVote(
                id=str(v.id),
                round_id=str(v.mix_id),
                submission_id=str(v.submission_id),
                weight=v.weight,
                created_at=v.created_at,
            )
            for v in votes
        ],
        notes=[
            ExportNote(
                id=str(n.id),
                round_id=str(n.mix_id),
                submission_id=str(n.submission_id),
                body=n.body,
                created_at=n.created_at,
            )
            for n in notes
        ],
        club_memberships=[
            ExportClubMembership(
                league_id=str(member.club_id),
                league_name=club_name,
                role=member.role,
                joined_at=member.joined_at,
            )
            for member, club_name in memberships
        ],
    )


# --------------------------------------------------------------------------- #
# My submission history (MysteryMixClub-ps1w.1): every song the caller has
# ever submitted, across every club, for a sortable/searchable profile view.
# --------------------------------------------------------------------------- #


class MySubmissionEntry(WireModel):
    submission_id: str
    league_id: str
    league_name: str
    round_id: str
    round_number: int
    theme: str | None
    state: str
    # None for a source-only track; source/source_url identify it instead (MYS-201).
    isrc: str | None
    source: Literal["youtube", "bandcamp"] | None = None
    source_url: str | None = None
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    # The submitter's own optional note attached at submission time.
    submitter_note: str | None
    # Notes others left on this submission. Gated exactly like
    # GET /submissions/:id/notes: hidden from everyone but their own author
    # while the mix's voting is open, fully revealed once it closes (MYS-67).
    notes: list[ResultNote]
    # Vote identity stays anonymous until the mix closes (MYS-173) -- null
    # rather than 0 for an open mix, so the client can't mistake "hidden" for
    # "actually zero votes so far".
    vote_count: int | None
    voters: list[ResultVoter]
    created_at: datetime


@router.get("/me/submissions", response_model=list[MySubmissionEntry])
async def get_my_submission_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MySubmissionEntry]:
    """Every song the caller has ever submitted, newest first.

    Sorting/searching happen client-side over this one list, the same way
    ProfileRoute already treats archived clubs -- there's no pagination
    convention elsewhere in the API, and this app's invite-only, friend-group
    scale doesn't call for introducing one here.
    """
    rows = (
        await db.execute(
            select(Submission, Mix, Club.name)
            .join(Mix, Mix.id == Submission.mix_id)
            .join(Club, Club.id == Mix.club_id)
            .where(Submission.user_id == current_user.id)
            .order_by(Submission.created_at.desc())
        )
    ).all()
    if not rows:
        return []

    submission_ids = [s.id for s, _mix, _name in rows]
    closed_submission_ids = {s.id for s, mix_, _name in rows if mix_.state == "closed"}

    vote_counts: dict[uuid.UUID, int] = {}
    voters_by_submission: dict[uuid.UUID, list[ResultVoter]] = {}
    if closed_submission_ids:
        vote_count_rows = (
            await db.execute(
                select(Vote.submission_id, func.sum(Vote.weight))
                .where(Vote.submission_id.in_(closed_submission_ids))
                .group_by(Vote.submission_id)
            )
        ).all()
        vote_counts = {sid: count for sid, count in vote_count_rows}

        voter_rows = (
            await db.execute(
                select(Vote.submission_id, Vote.voter_id, User.display_name, Vote.weight)
                .join(User, User.id == Vote.voter_id)
                .where(Vote.submission_id.in_(closed_submission_ids))
            )
        ).all()
        for submission_id, voter_id, display_name, weight in voter_rows:
            voters_by_submission.setdefault(submission_id, []).append(
                ResultVoter(user_id=str(voter_id), display_name=display_name, weight=weight)
            )
        for voters in voters_by_submission.values():
            voters.sort(key=lambda v: v.display_name)

    note_rows = (
        await db.execute(
            select(Note, User.display_name, Mix.state)
            .join(User, User.id == Note.author_id)
            .join(Mix, Mix.id == Note.mix_id)
            .where(Note.submission_id.in_(submission_ids))
            .order_by(Note.created_at.asc())
        )
    ).all()
    notes_by_submission: dict[uuid.UUID, list[ResultNote]] = {}
    for note, display_name, mix_state in note_rows:
        # Mirrors GET /submissions/:id/notes: a member (including the
        # submitter) sees only their own notes while voting is open, so notes
        # can't sway votes (MYS-67); the full set is revealed once closed.
        if mix_state != "closed" and note.author_id != current_user.id:
            continue
        notes_by_submission.setdefault(note.submission_id, []).append(
            ResultNote(body=note.body, author_display_name=display_name, created_at=note.created_at)
        )

    return [
        MySubmissionEntry(
            submission_id=str(s.id),
            league_id=str(mix_.club_id),
            league_name=club_name,
            round_id=str(mix_.id),
            round_number=mix_.mix_number,
            theme=mix_.theme,
            state=mix_.state,
            isrc=s.isrc,
            source=source_fields(s.source_key)[0],
            source_url=source_fields(s.source_key)[1],
            title=s.title,
            artist=s.artist,
            album=s.album,
            album_art_url=s.album_art_url,
            submitter_note=s.note,
            notes=notes_by_submission.get(s.id, []),
            vote_count=vote_counts.get(s.id, 0) if s.id in closed_submission_ids else None,
            voters=voters_by_submission.get(s.id, []),
            created_at=s.created_at,
        )
        for s, mix_, club_name in rows
    ]


@router.patch("/me", response_model=UserProfileResponse)
async def update_me(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserProfileResponse:
    fields = payload.model_dump(exclude_unset=True, exclude={"accept_terms"})
    for field, value in fields.items():
        setattr(current_user, field, value)
    if payload.accept_terms:
        current_user.tos_accepted_at = datetime.now(timezone.utc)
    await db.commit()
    return await _to_profile(current_user, settings, db)


# Calm, actionable detail when the caller still organizes a live club.
_ACTIVE_CLUB_BLOCK = "finish or hand off the clubs you organize before deleting your account"


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete the caller's account (right to be forgotten, TD 10).

    Blocks while the caller organizes an active club. Otherwise it tombstones
    the email (freeing it for re-signup and dropping the PII), invalidates every
    session, and marks the account deleted. Submissions/votes/notes/memberships
    are left intact for mix integrity and are removed by the scheduled hard
    purge within 30 days (app.jobs.purge_accounts). The existing deleted_at
    filters in auth already lock the account out of sign-in.
    """
    organizes_active = await db.scalar(
        select(func.count())
        .select_from(Club)
        .where(Club.organizer_id == current_user.id, Club.state == "active")
    )
    if organizes_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_ACTIVE_CLUB_BLOCK,
        )

    now = datetime.now(timezone.utc)
    former_email = current_user.email
    # The email-keyed reset tokens FIRST, before the user row is touched: password
    # reset takes its token row and then the user, so taking them in the other
    # order here deadlocks with a reset in flight (a cycle that predates
    # MysteryMixClub-4vii.36 and that its stress test exposed; ADR 0034).
    await db.execute(delete(PasswordResetToken).where(PasswordResetToken.email == former_email))
    current_user.deleted_at = now
    current_user.email = f"deleted+{current_user.id}@deleted.invalid"
    # Drop every credential and anything else keyed to the real address, while
    # that address is still known — after the tombstone above it can't be
    # matched again (ADR 0007). google_id/auth_identities rows are third-party
    # identifiers for a person who asked to be forgotten, so they go for the
    # same reason as the password hash (TD 10), not merely because they're
    # UNIQUE: leaving them would also make the same provider account's next
    # sign-up collide with a tombstone the resolution queries can no longer
    # see (MysteryMixClub-4vii.9 generalized this from google_id alone).
    current_user.password_hash = None
    current_user.google_id = None
    await db.execute(delete(AuthIdentity).where(AuthIdentity.user_id == current_user.id))
    # Kill every still-active session so refresh tokens die with the account.
    # This comes BEFORE the device delete below on purpose: logout, logout-all,
    # password reset and push registration all take a session and then a device
    # row, and the opposite order here deadlocks with a concurrent logout
    # (MysteryMixClub-4vii.36, ADR 0034). This is a local ordering for the writers
    # that touch device rows, not a global lock order for the codebase.
    await db.execute(
        update(Session)
        .where(Session.user_id == current_user.id, Session.invalidated_at.is_(None))
        .values(invalidated_at=now)
    )
    # Same reasoning as AuthIdentity above -- a forgotten account's device
    # shouldn't keep receiving its old club's pushes (MysteryMixClub-4vii.25).
    await db.execute(delete(DevicePushToken).where(DevicePushToken.user_id == current_user.id))
    await db.execute(delete(LoginAttempt).where(LoginAttempt.email == former_email))

    await db.commit()


# --------------------------------------------------------------------------- #
# Push notification device registration (MysteryMixClub-4vii.25, IOS-04).
# --------------------------------------------------------------------------- #


class RegisterPushTokenRequest(WireModel):
    device_token: str = Field(min_length=1, max_length=512)


class RegisterPushTokenResponse(WireModel):
    message: str = "registered"


@router.post("/me/push-token", response_model=RegisterPushTokenResponse)
async def register_push_token(
    payload: RegisterPushTokenRequest,
    current_user: User = Depends(get_current_user),
    session_id: uuid.UUID | None = Depends(get_current_session_id),
    db: AsyncSession = Depends(get_db),
) -> RegisterPushTokenResponse:
    """Register (or re-register) a device for push notifications.

    Upsert by `device_token`, not by (user, token): a device can only ever
    receive push for one account at a time, so a token that already exists --
    same device signing in as someone else, or simply re-registering on
    launch -- gets reassigned to the caller rather than erroring or leaving a
    stale second row. One user can have many rows (many devices); this never
    touches any row but the one matching this exact token.

    The registration is bound to the login session the access token was issued
    under (MysteryMixClub-4vii.36), because an access token stays valid for up
    to an hour after logout and an upload can be in flight when logout runs:

    - The session must be live. It is read FOR SHARE, and /auth/logout takes the
      same row FOR UPDATE, so a registration either commits before logout (and
      logout deletes it) or runs after and is refused -- it can never recreate a
      row for an account that has signed out. Refused with the same neutral 401
      as any other unauthenticated request.
    - A token already held by another session is only taken over by a session
      that is at least as new. A late upload from an older login (the previous
      account, on a phone that has since signed in as someone else) therefore
      cannot overwrite the newer account's ownership; refused with 409.
    - A token issued before the claim existed carries no session and keeps the
      previous unconditional behaviour (those tokens expire within the hour).
    """
    # Lock order matters: USERS row first, then the session. Account deletion
    # (`delete_me`) takes the users row exclusively (a key update on the unique
    # email) and only afterwards touches sessions. Registration used to take the
    # session row (FOR SHARE) and only reach the users row later, through the
    # device insert's foreign key; those opposite orders deadlock (reproduced
    # with two connections). So take the user row first, in the weakest mode that
    # still conflicts with that: FOR KEY SHARE. (The admin eject of a LIVE account,
    # `hard_delete_users`, deletes sessions and reaches the users row last, so it
    # can still deadlock with a registration racing it; see ADR 0034 "Known
    # limits". It is admin-initiated and one of the two requests fails cleanly.) It does NOT conflict with
    # changes to non-key columns (a profile edit, a password change, a ToS
    # acceptance), so ordinary account activity never blocks a registration.
    # SQLAlchemy needs BOTH flags for that mode: `key_share=True` alone compiles
    # to FOR NO KEY UPDATE, which does. Re-reading under the lock means a user
    # who was deleted (soft or hard) a moment ago is refused even when the token
    # carries no session: a hard-deleted user has no row at all.
    user_row = (
        await db.execute(
            select(User.deleted_at)
            .where(User.id == current_user.id)
            .with_for_update(read=True, key_share=True)
        )
    ).one_or_none()
    if user_row is None or user_row.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    session_created_at = None
    if session_id is not None:
        session = await db.scalar(
            select(Session)
            .where(Session.id == session_id, Session.user_id == current_user.id)
            .with_for_update(read=True)
        )
        if session is None or not session_is_live(session, datetime.now(timezone.utc)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
            )
        session_created_at = session.created_at

    # One atomic upsert (not select-then-write): a dead-token verdict from APNs
    # only retires a registration that predates it, so every registration --
    # new, reassigned, or the same user re-registering -- stamps `updated_at`
    # itself, and a concurrent retire can neither make this a no-op nor raise.
    # clock_timestamp(), not now(), so it is the moment of this statement
    # rather than the transaction's start (MysteryMixClub-4vii.33).
    takeover_allowed = None
    if session_created_at is not None:
        # The conflicting row's own session_id, named literally. In an ON CONFLICT
        # ... WHERE there is no enclosing SELECT for SQLAlchemy to correlate
        # against (`.correlate()` does nothing here), so referencing the mapped
        # column would compile to `FROM sessions, device_push_tokens`: the
        # subquery would then span the whole table and, once two or more bound
        # rows exist, raise "more than one row returned by a subquery" (a 500).
        # A literal column adds no FROM item, so this stays tied to the one row.
        conflicting_row_session_id = literal_column(
            f"{DevicePushToken.__tablename__}.session_id", type_=DevicePushToken.session_id.type
        )
        owner_session_created_at = (
            select(Session.created_at)
            .where(Session.id == conflicting_row_session_id)
            .scalar_subquery()
        )
        takeover_allowed = or_(
            DevicePushToken.session_id.is_(None),
            owner_session_created_at <= session_created_at,
        )
    registered = await db.scalar(
        insert(DevicePushToken)
        .values(
            user_id=current_user.id,
            device_token=payload.device_token,
            session_id=session_id,
            updated_at=func.clock_timestamp(),
        )
        .on_conflict_do_update(
            index_elements=[DevicePushToken.device_token],
            set_={
                "user_id": current_user.id,
                "session_id": session_id,
                "updated_at": func.clock_timestamp(),
            },
            where=takeover_allowed,
        )
        .returning(DevicePushToken.id)
    )
    if registered is None:
        # The conflicting row belongs to a newer sign-in: this request is stale.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this device was registered by a newer sign-in",
        )
    await db.commit()
    return RegisterPushTokenResponse()


@router.delete("/me/push-token", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_push_token(
    device_token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a device's push registration (called on logout, MysteryMixClub-
    4vii.25/PRD IOS-04: "remove account associations on logout or deletion").
    Scoped to the caller's own rows -- deleting a token registered to a
    different account is a no-op, not an error, since the caller has no way
    to know that happened and there's nothing actionable to tell them."""
    await db.execute(
        delete(DevicePushToken).where(
            DevicePushToken.device_token == device_token,
            DevicePushToken.user_id == current_user.id,
        )
    )
    await db.commit()


# --------------------------------------------------------------------------- #
# Account settings: opt an existing account into password / Google sign-in
# (MysteryMixClub-ali8.4, ADR 0007). No forced migration -- an account that
# never calls these keeps working exactly as it does today.
# --------------------------------------------------------------------------- #

_PASSWORD_ALREADY_SET_MESSAGE = (
    "a password is already set on this account -- use forgot-password to change it"
)


class SetPasswordRequest(WireModel):
    password: str = Field(min_length=_PASSWORD_MIN_LENGTH, max_length=_PASSWORD_MAX_LENGTH)


class SetPasswordResponse(WireModel):
    message: str = "password set"


class GoogleLinkStartResponse(WireModel):
    authorize_url: str


@router.post(
    "/me/password", response_model=SetPasswordResponse, status_code=status.HTTP_201_CREATED
)
async def set_password(
    payload: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SetPasswordResponse:
    """Opt an existing magic-link/Google-only account into password sign-in.

    Only for an account with no password yet. Changing an existing password
    goes through /auth/forgot-password + /auth/reset-password instead, which
    also invalidates every other session the way a credential change should --
    this endpoint doesn't, since setting a *first* password from an
    already-signed-in session isn't a compromise-recovery action.
    """
    if current_user.password_hash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=_PASSWORD_ALREADY_SET_MESSAGE
        )

    # Off the event loop, same reason as every other argon2 hash in this app
    # (app/api/routes/auth.py): a synchronous hash would block every other
    # request on this worker for its whole duration.
    current_user.password_hash = await asyncio.to_thread(hash_password, payload.password)
    await db.commit()
    return SetPasswordResponse()


@router.get("/me/google/link", response_model=GoogleLinkStartResponse)
async def start_google_link(
    response: Response,
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    client: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> GoogleLinkStartResponse:
    """Start linking a Google identity onto the caller's existing account.

    Returns Google's consent URL as JSON (like /spotify/connect) rather than
    redirecting directly: this is an authenticated fetch call carrying a Bearer
    token, and a top-level browser navigation can't carry one, so the frontend
    does the actual redirect to ``authorize_url`` itself once it has it.

    Sets the same anti-CSRF nonce cookie the sign-in flow uses (shared cookie
    name/path -- only one Google round-trip is ever in flight per browser at a
    time), which /auth/google/callback checks against this state's nonce
    before linking anything (see create_google_link_state's docstring for why
    that check matters here specifically).
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_GOOGLE_UNCONFIGURED_MESSAGE
        )

    nonce = generate_token()
    code_verifier, code_challenge = generate_pkce_pair()
    state = create_google_link_state(current_user.id, nonce, code_verifier)
    response.set_cookie(
        key=_GOOGLE_NONCE_COOKIE_NAME,
        value=nonce,
        max_age=_GOOGLE_NONCE_MAX_AGE,
        path=_GOOGLE_NONCE_COOKIE_PATH,
        httponly=True,
        samesite=_GOOGLE_NONCE_SAMESITE,
        secure=settings.secure_cookies,
    )
    return GoogleLinkStartResponse(authorize_url=client.authorize_url(state, code_challenge))
