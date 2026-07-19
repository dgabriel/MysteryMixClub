"""Spotify connect + per-round playlist creation (MYS-83, MYS-169).

* ``GET  /spotify/connect``  — (auth) start OAuth; returns the consent URL.
* ``GET  /spotify/callback`` — (no auth) Spotify redirects here; we exchange the
  code, store the encrypted refresh token, and bounce back to the SPA. The user
  identity rides in a signed ``state`` token (the callback has no bearer header).
* ``GET  /spotify/status``   — (auth) is the app configured / is the shared
  playlist account connected.
* ``DELETE /spotify/connection`` — (auth) disconnect (own connection only).
* ``GET  /rounds/:id/spotify-playlist`` — (auth, any league member) read-only:
  the round's existing playlist link, or null if none has been generated yet.

Token exchange/refresh is server-side; the client secret and refresh token never
reach the browser.

MYS-169: Spotify's extended quota requires 250k MAU, so the app stays in
Development Mode indefinitely (~25 allowlisted accounts platform-wide) — per-user
OAuth playlist creation is dead as a general feature. One designated
MysteryMixClub Spotify account (``settings.spotify_playlist_account_user_id``)
creates each round's playlist as PUBLIC; every member gets the same link.

Generation is automatic, triggered on the ``voting_open`` event (MYS-176) via
:func:`app.services.spotify_playlist_generation.try_auto_generate_playlist` —
there is no manual/admin trigger. Regular members only ever read the resulting
link through this router. The connect/callback/status endpoints and per-user
connection storage stay dormant (not deleted) in case extended quota is ever
reached.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.wire import WireModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member
from app.api.routes.rounds import _load_round
from app.auth.deps import get_current_user
from app.auth.jwt import JWTError, create_oauth_state, decode_oauth_state
from app.config import Settings, get_settings
from app.db.session import get_db
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
    get_shared_connection,
    playlist_account_user_id,
)
from app.services.spotify_token_crypto import encrypt_refresh_token

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


class ConnectResponse(WireModel):
    authorize_url: str


class StatusResponse(WireModel):
    # Whether the server has Spotify app credentials at all (drives whether the
    # UI shows the feature). False on environments where the secret isn't set.
    configured: bool
    connected: bool


class UnmatchedTrack(WireModel):
    submission_id: uuid.UUID
    title: str
    artist: str
    # Why it was skipped (MYS-201): "source_only" — a Bandcamp/YouTube track with
    # no ISRC that can never match Spotify's catalog — vs "no_catalog_match", an
    # ISRC-backed track Spotify's catalog just doesn't carry. Lets the gap summary
    # say why rather than only how many.
    reason: Literal["source_only", "no_catalog_match"]


class SpotifyPlaylistLinkResponse(WireModel):
    """The round page's read-only view (MYS-169/MYS-176): just the link, or null
    if generation hasn't run (or hasn't matched anything) yet.

    ``unmatched`` (MYS-201) accompanies an existing playlist and lists the round's
    submissions that didn't make it, with a reason — empty when there's no
    playlist yet (nothing generated, or nothing matched)."""

    playlist_url: str | None
    unmatched: list[UnmatchedTrack] = []


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
# Playlist link (read-only — generation is automatic, see MYS-176)
# --------------------------------------------------------------------------- #


@router.get("/mixes/{round_id}/spotify-playlist", response_model=SpotifyPlaylistLinkResponse)
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

    # The gap summary (MYS-201) is recomputed from persisted state, not stored:
    # auto-generation caches each matched track's spotify_track_uri on the
    # submission, so a submission with no cached uri is exactly one the playlist
    # skipped. The reason mirrors the generator — no ISRC means a source-only
    # (Bandcamp/YouTube) track that can never match, otherwise the catalog simply
    # doesn't carry it. No Spotify call needed: the classification is the same one
    # generate_round_playlist made when it built the playlist.
    submissions = await db.scalars(
        select(Submission).where(Submission.round_id == round_id).order_by(Submission.id)
    )
    unmatched = [
        UnmatchedTrack(
            submission_id=s.id,
            title=s.title,
            artist=s.artist,
            reason="source_only" if not s.isrc else "no_catalog_match",
        )
        for s in submissions
        if not s.spotify_track_uri
    ]
    return SpotifyPlaylistLinkResponse(
        playlist_url=f"https://open.spotify.com/playlist/{stored.playlist_id}",
        unmatched=unmatched,
    )


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
