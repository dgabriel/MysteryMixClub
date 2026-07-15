"""Spotify connect + per-round playlist creation (MYS-83, MYS-169).

* ``GET  /spotify/connect``  — (auth) start OAuth; returns the consent URL.
* ``GET  /spotify/callback`` — (no auth) Spotify redirects here; we exchange the
  code, store the encrypted refresh token, and bounce back to the SPA. The user
  identity rides in a signed ``state`` token (the callback has no bearer header).
* ``GET  /spotify/status``   — (auth) is the app configured / is the shared
  playlist account connected.
* ``DELETE /spotify/connection`` — (auth) disconnect (own connection only).
* ``POST /rounds/:id/spotify-playlist`` — (platform-admin only) resolve the
  round's submissions to Spotify track URIs and create/refresh a PUBLIC playlist
  owned by the shared account.
* ``GET  /rounds/:id/spotify-playlist`` — (auth, any league member) read-only:
  the round's existing playlist link, or null if the admin hasn't generated one.
* ``GET  /admin/rounds/spotify-pending`` — (platform-admin only) every live
  round across every league, for the admin screen's generate/regenerate list.

Token exchange/refresh is server-side; the client secret and refresh token never
reach the browser.

MYS-169: Spotify's extended quota requires 250k MAU, so the app stays in
Development Mode indefinitely (~25 allowlisted accounts platform-wide) — per-user
OAuth playlist creation is dead as a general feature. One designated
MysteryMixClub Spotify account (``settings.spotify_playlist_account_user_id``)
creates each round's playlist as PUBLIC; every member gets the same link.

Generation is **platform-admin only**, not any league member (revised
2026-07-03): the shared account is a real person's own Spotify account, and
letting every league member trigger writes against it was judged too broad a
surface for Spotify's Dev Mode single-user framing. An admin generates/refreshes
from a dedicated admin-screen list; regular members only ever read the
resulting link. The connect/callback/status endpoints and per-user connection
storage stay dormant (not deleted) in case extended quota is ever reached.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member
from app.api.routes.rounds import _load_round
from app.auth.deps import get_current_user, get_platform_admin
from app.auth.jwt import JWTError, create_oauth_state, decode_oauth_state
from app.config import Settings, get_settings
from app.db.session import get_db
from app.models.league import League
from app.models.round import Round
from app.models.spotify_connection import SpotifyConnection
from app.models.spotify_round_playlist import SpotifyRoundPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.services.spotify_client import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyClient,
    get_spotify_client,
)
from app.services.spotify_playlist_generation import (
    generate_round_playlist,
    get_shared_connection,
    playlist_account_user_id,
)
from app.services.spotify_token_crypto import SpotifyTokenCryptoError, encrypt_refresh_token

# Rounds in these states can have a meaningful playlist (mirrors the generation
# gate: submissions are locked once open_submission ends).
_PLAYLIST_ELIGIBLE_STATES = ("open_voting", "closed")

router = APIRouter(tags=["spotify"])
logger = logging.getLogger("app.api.routes.spotify")

_OAUTH_PURPOSE = "spotify"


def _safe_return_path(path: str | None) -> str | None:
    """Accept only an in-app **absolute path** (e.g. ``/rounds/<id>``) to guard
    against open-redirect — the callback concatenates this onto our own base URL.
    Rejects anything not single-slash-rooted, protocol-relative (``//``), or
    carrying a scheme/backslash/newline."""
    if not path or not path.startswith("/") or path.startswith("//"):
        return None
    if "://" in path or "\\" in path or "\n" in path or "\r" in path:
        return None
    return path


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class ConnectResponse(BaseModel):
    authorize_url: str


class StatusResponse(BaseModel):
    # Whether the server has Spotify app credentials at all (drives whether the
    # UI shows the feature). False on environments where the secret isn't set.
    configured: bool
    connected: bool


class UnmatchedTrack(BaseModel):
    submission_id: str
    title: str
    artist: str


class SpotifyPlaylistResponse(BaseModel):
    round_id: str
    # None when nothing matched (no playlist is created for an empty track set).
    playlist_url: str | None
    # Tracks matched and added to the playlist.
    track_count: int
    # Total submissions in the round (so the UI can show "N of M").
    total_count: int
    unmatched: list[UnmatchedTrack]


class SpotifyPlaylistLinkResponse(BaseModel):
    """The round page's read-only view (MYS-169): just the link, or null if an
    admin hasn't generated one yet. No match counts — those are an admin-screen
    concern, surfaced at generation time via :class:`SpotifyPlaylistResponse`."""

    playlist_url: str | None


class AdminSpotifyRoundResponse(BaseModel):
    """One row on the admin screen's generate/regenerate list (MYS-169)."""

    round_id: str
    league_name: str
    round_label: str
    state: str
    submission_count: int
    # Present if an admin has already generated/refreshed this round's playlist.
    playlist_url: str | None


# --------------------------------------------------------------------------- #
# Connect / callback / status
# --------------------------------------------------------------------------- #


@router.get("/spotify/connect", response_model=ConnectResponse)
async def spotify_connect(
    return_to: str | None = None,
    current_user: User = Depends(get_current_user),
    client: SpotifyClient = Depends(get_spotify_client),
) -> ConnectResponse:
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify is not configured on this server",
        )
    # `return_to` (e.g. the round that started the connect) rides in the signed
    # state so the callback can land the user back where they were (MYS-93).
    state = create_oauth_state(current_user.id, _OAUTH_PURPOSE, _safe_return_path(return_to))
    return ConnectResponse(authorize_url=client.authorize_url(state))


@router.get("/spotify/callback")
async def spotify_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    client: SpotifyClient = Depends(get_spotify_client),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Spotify redirects here after consent. Validates state, exchanges the code,
    persists the connection, and bounces back to the SPA — to the round the user
    started from (``return_to`` in the state), else ``/home``.

    Note the landing is an authenticated route, never ``/`` — the root route
    unconditionally redirects to ``/login`` and would strand the still-authenticated
    user on the login page (MYS-92)."""

    def _redirect(path: str, flag: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"{settings.app_base_url}{path}?spotify={flag}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # A bad/expired state can't be trusted to carry a return path → fall back home.
    try:
        oauth_state = decode_oauth_state(state, _OAUTH_PURPOSE)
    except JWTError:
        return _redirect("/home", "error")
    return_to = _safe_return_path(oauth_state.return_to) or "/home"

    if error or not code:
        # User denied consent or Spotify returned an error before a code was issued.
        logger.info("spotify callback: denied or no code (error=%s)", error)
        return _redirect(return_to, "denied")

    try:
        tokens = await client.exchange_code(code)
    except (SpotifyAuthError, SpotifyApiError):
        # MYS-169: distinct flag + full exception (carries the Spotify error body
        # via spotify_client's _safe_body) so a swallowed failure is diagnosable.
        logger.exception("spotify callback: code exchange failed")
        return _redirect(return_to, "exchange_failed")

    if not tokens.refresh_token:
        # Initial authorization must include a refresh token; without it we
        # can't mint future access tokens.
        logger.error("spotify callback: exchange succeeded but returned no refresh_token")
        return _redirect(return_to, "exchange_failed")

    try:
        spotify_user_id = await client.get_current_user_id(tokens.access_token)
    except (SpotifyAuthError, SpotifyApiError):
        logger.exception("spotify callback: /me lookup failed after exchange")
        return _redirect(return_to, "api_error")

    await _upsert_connection(
        db,
        user_id=oauth_state.user_id,
        spotify_user_id=spotify_user_id,
        refresh_token=tokens.refresh_token,
        scope=tokens.scope,
    )
    return _redirect(return_to, "connected")


@router.get("/spotify/status", response_model=StatusResponse)
async def spotify_status(
    current_user: User = Depends(get_current_user),  # auth gate only
    db: AsyncSession = Depends(get_db),
    client: SpotifyClient = Depends(get_spotify_client),
    settings: Settings = Depends(get_settings),
) -> StatusResponse:
    """``connected`` now reflects the shared playlist account (MYS-169), not the
    calling user — every member sees the same status, since no one connects
    their own account anymore. Drives whether the round page shows the
    playlist affordance at all."""
    account_id = playlist_account_user_id(settings)
    connection = await get_shared_connection(db, account_id) if account_id else None
    return StatusResponse(configured=client.is_configured, connected=connection is not None)


@router.delete("/spotify/connection", status_code=status.HTTP_204_NO_CONTENT)
async def spotify_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    connection = await get_shared_connection(db, current_user.id)
    if connection is not None:
        await db.delete(connection)
        await db.commit()


# --------------------------------------------------------------------------- #
# Playlist creation
# --------------------------------------------------------------------------- #


@router.post("/rounds/{round_id}/spotify-playlist", response_model=SpotifyPlaylistResponse)
async def create_round_spotify_playlist(
    round_id: uuid.UUID,
    admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    client: SpotifyClient = Depends(get_spotify_client),
    settings: Settings = Depends(get_settings),
) -> SpotifyPlaylistResponse:
    """Generate/refresh a round's playlist (platform-admin only, MYS-169).

    Not gated on league membership — an admin manages playlists across every
    league, not just ones they personally play in — so the league is loaded
    directly rather than via :func:`_load_league_as_member`."""
    round_ = await _load_round(round_id, db)
    league = await db.scalar(select(League).where(League.id == round_.league_id))
    if league is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="league not found")
    # Mirror the voting playlist gate: the mix is only meaningful once submissions
    # are locked (the round has left open_submission).
    if round_.state == "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the playlist is available once voting opens",
        )

    # The playlist is always created/owned by the one shared account — never the
    # admin's own (dormant) connection unless that happens to be the same user.
    # A missing/broken shared connection is an ops issue, logged loudly here.
    account_id = playlist_account_user_id(settings)
    if account_id is None:
        logger.error("spotify playlist: SPOTIFY_PLAYLIST_ACCOUNT_USER_ID is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists aren't set up for this league yet",
        )
    connection = await get_shared_connection(db, account_id)
    if connection is None:
        logger.error("spotify playlist: shared account %s has no spotify connection", account_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists aren't set up for this league yet",
        )

    try:
        result = await generate_round_playlist(
            round_id, round_, league, account_id, connection, db, client
        )
    except SpotifyTokenCryptoError as exc:
        logger.exception("spotify playlist: shared account refresh token failed to decrypt")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists are temporarily unavailable — try again later",
        ) from exc
    except SpotifyAuthError as exc:
        # Single point of failure (MYS-169): a revoked grant on the shared
        # account breaks generation platform-wide until an admin reconnects
        # it. The caller can't fix this themselves, so log loudly here.
        logger.exception("spotify playlist: shared account %s authorization rejected", account_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists are temporarily unavailable — try again later",
        ) from exc
    except SpotifyApiError as exc:
        logger.exception("spotify playlist: spotify API call failed for round %s", round_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="spotify couldn't create the playlist — try again",
        ) from exc

    return SpotifyPlaylistResponse(
        round_id=str(round_.id),
        playlist_url=result.playlist_url,
        track_count=result.track_count,
        total_count=result.total_count,
        unmatched=[
            UnmatchedTrack(submission_id=str(u.submission_id), title=u.title, artist=u.artist)
            for u in result.unmatched
        ],
    )


@router.get("/rounds/{round_id}/spotify-playlist", response_model=SpotifyPlaylistLinkResponse)
async def get_round_spotify_playlist_link(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SpotifyPlaylistLinkResponse:
    """The round page's read-only view (MYS-169): any league member can read the
    link an admin already generated, but never trigger generation themselves.
    Null (not an error) whenever nothing's been generated yet, the shared
    account isn't configured, or this member simply isn't in the league."""
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)

    account_id = playlist_account_user_id(settings)
    if account_id is None:
        return SpotifyPlaylistLinkResponse(playlist_url=None)

    stored = await db.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == account_id,
        )
    )
    if stored is None:
        return SpotifyPlaylistLinkResponse(playlist_url=None)
    return SpotifyPlaylistLinkResponse(
        playlist_url=f"https://open.spotify.com/playlist/{stored.playlist_id}"
    )


@router.get("/admin/rounds/spotify-pending", response_model=list[AdminSpotifyRoundResponse])
async def list_spotify_pending_rounds(
    _admin: User = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[AdminSpotifyRoundResponse]:
    """Every live (open_voting/closed) round with at least one submission, across
    every league, for the admin screen's generate/regenerate list (MYS-169).
    Rounds with zero submissions are excluded — generation can never produce a
    playlist for them (matched_uris is always empty), so listing them is noise.
    Most recently active first."""
    account_id = playlist_account_user_id(settings)

    submission_counts = (
        select(Submission.round_id, func.count().label("submission_count"))
        .group_by(Submission.round_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            Round,
            League.name,
            submission_counts.c.submission_count,
            SpotifyRoundPlaylist.playlist_id,
        )
        .join(League, League.id == Round.league_id)
        .join(submission_counts, submission_counts.c.round_id == Round.id)
        .outerjoin(
            SpotifyRoundPlaylist,
            (SpotifyRoundPlaylist.round_id == Round.id)
            & (SpotifyRoundPlaylist.user_id == account_id),
        )
        .where(Round.state.in_(_PLAYLIST_ELIGIBLE_STATES))
        .order_by(func.coalesce(Round.closed_at, Round.created_at).desc())
    )
    return [
        AdminSpotifyRoundResponse(
            round_id=str(round_.id),
            league_name=league_name,
            round_label=(
                f"Round {round_.round_number}: {round_.theme}"
                if round_.theme
                else f"Round {round_.round_number}"
            ),
            state=round_.state,
            submission_count=submission_count,
            playlist_url=(
                f"https://open.spotify.com/playlist/{playlist_id}" if playlist_id else None
            ),
        )
        for round_, league_name, submission_count, playlist_id in rows.all()
    ]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _upsert_connection(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    spotify_user_id: str,
    refresh_token: str,
    scope: str | None,
) -> None:
    connection = await get_shared_connection(db, user_id)
    encrypted = encrypt_refresh_token(refresh_token)
    if connection is None:
        db.add(
            SpotifyConnection(
                user_id=user_id,
                spotify_user_id=spotify_user_id,
                refresh_token_encrypted=encrypted,
                scope=scope,
            )
        )
    else:
        connection.spotify_user_id = spotify_user_id
        connection.refresh_token_encrypted = encrypted
        connection.scope = scope
    await db.commit()
