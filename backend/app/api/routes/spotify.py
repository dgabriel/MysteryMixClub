"""Spotify connect + per-round playlist creation (MYS-83, MYS-169).

Three surfaces:

* ``GET  /spotify/connect``  — (auth) start OAuth; returns the consent URL.
* ``GET  /spotify/callback`` — (no auth) Spotify redirects here; we exchange the
  code, store the encrypted refresh token, and bounce back to the SPA. The user
  identity rides in a signed ``state`` token (the callback has no bearer header).
* ``GET  /spotify/status``   — (auth) is the app configured / is the shared
  playlist account connected.
* ``DELETE /spotify/connection`` — (auth) disconnect (own connection only).
* ``POST /rounds/:id/spotify-playlist`` — (auth, any league member) resolve the
  round's submissions to Spotify track URIs and create a PUBLIC playlist owned
  by the shared account; returns the link plus any tracks we couldn't match
  (the "unmatched" escape hatch). Same link for every caller.

Token exchange/refresh is server-side; the client secret and refresh token never
reach the browser.

MYS-169: Spotify's extended quota requires 250k MAU, so the app stays in
Development Mode indefinitely (~25 allowlisted accounts platform-wide) — per-user
OAuth playlist creation is dead as a general feature. One designated
MysteryMixClub Spotify account (``settings.spotify_playlist_account_user_id``)
creates each round's playlist as PUBLIC; every member gets the same link, no
Spotify connection of their own required. The connect/callback/status endpoints
and per-user connection storage stay dormant (not deleted) in case extended
quota is ever reached.
"""

from __future__ import annotations

import logging
import random
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
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
    SpotifyNotFoundError,
    get_spotify_client,
)
from app.services.spotify_playlist import playlist_description, playlist_name
from app.services.spotify_token_crypto import (
    SpotifyTokenCryptoError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)

router = APIRouter(tags=["spotify"])
logger = logging.getLogger("app.api.routes.spotify")

_OAUTH_PURPOSE = "spotify"


def _playlist_account_user_id(settings: Settings) -> uuid.UUID | None:
    """The shared playlist account's app-user id, or ``None`` when unset/invalid
    (MYS-169) — playlist generation is unavailable until this is configured."""
    raw = settings.spotify_playlist_account_user_id
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.error("SPOTIFY_PLAYLIST_ACCOUNT_USER_ID is not a valid UUID: %r", raw)
        return None


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
    account_id = _playlist_account_user_id(settings)
    connection = await _get_connection(db, account_id) if account_id else None
    return StatusResponse(configured=client.is_configured, connected=connection is not None)


@router.delete("/spotify/connection", status_code=status.HTTP_204_NO_CONTENT)
async def spotify_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    connection = await _get_connection(db, current_user.id)
    if connection is not None:
        await db.delete(connection)
        await db.commit()


# --------------------------------------------------------------------------- #
# Playlist creation
# --------------------------------------------------------------------------- #


@router.post("/rounds/{round_id}/spotify-playlist", response_model=SpotifyPlaylistResponse)
async def create_round_spotify_playlist(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client: SpotifyClient = Depends(get_spotify_client),
    settings: Settings = Depends(get_settings),
) -> SpotifyPlaylistResponse:
    round_ = await _load_round(round_id, db)
    league = await _load_league_as_member(round_.league_id, current_user, db)
    # Mirror the voting playlist gate: the mix is only meaningful once submissions
    # are locked (the round has left open_submission).
    if round_.state == "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the playlist is available once voting opens",
        )

    # MYS-169: any league member may trigger generation, but the playlist is
    # always created/owned by the one shared account — never the caller's own
    # (dormant) connection. A missing/broken shared connection is an ops issue,
    # not something this member can fix, so it's logged loudly here.
    account_id = _playlist_account_user_id(settings)
    if account_id is None:
        logger.error("spotify playlist: SPOTIFY_PLAYLIST_ACCOUNT_USER_ID is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists aren't set up for this league yet",
        )
    connection = await _get_connection(db, account_id)
    if connection is None:
        logger.error("spotify playlist: shared account %s has no spotify connection", account_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists aren't set up for this league yet",
        )

    access_token = await _playlist_account_access_token(client, db, connection)

    submissions = list(await db.scalars(select(Submission).where(Submission.round_id == round_id)))
    # Same seeded shuffle as get_round_playlist so Spotify and YouTube always agree (MYS-151).
    # Sort first for a stable input — Postgres order without ORDER BY is not guaranteed.
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    matched_uris: list[str] = []
    unmatched: list[UnmatchedTrack] = []
    app_token = await client.app_access_token()
    cached_anything = False

    for s in submissions:
        uri = s.spotify_track_uri
        if not uri and app_token:
            uri = await client.search_track_uri_by_isrc(s.isrc, app_token)
            if uri:
                s.spotify_track_uri = uri
                cached_anything = True
        if uri:
            matched_uris.append(uri)
        else:
            unmatched.append(
                UnmatchedTrack(submission_id=str(s.id), title=s.title, artist=s.artist)
            )

    # Best-effort: persist newly resolved URIs, but never fail the request on the
    # cache write — the playlist is built from the in-memory uris regardless.
    if cached_anything:
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    name = playlist_name(league.name, round_.round_number, round_.theme)
    description = playlist_description(league.name, round_.round_number, round_.theme)

    # Keyed by (round, shared account) — since the account is the same for every
    # caller, this is effectively one playlist per round (MYS-169).
    stored = await db.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == account_id,
        )
    )

    playlist_url: str | None = None
    if matched_uris:
        try:
            if stored is not None:
                try:
                    # Reuse by stored ID — O(1), rename-proof, collision-free (MYS-89).
                    await client.replace_tracks(access_token, stored.playlist_id, matched_uris)
                    playlist_url = f"https://open.spotify.com/playlist/{stored.playlist_id}"
                except SpotifyNotFoundError:
                    # Playlist was deleted in Spotify; recreate and update stored ID.
                    playlist_id, playlist_url = await client.create_playlist(
                        access_token, name, description, public=True
                    )
                    await client.add_tracks(access_token, playlist_id, matched_uris)
                    stored.playlist_id = playlist_id
                    await db.commit()
            else:
                # Public (MYS-169): no API access needed to open the link, same
                # reach as the YouTube playlist link.
                playlist_id, playlist_url = await client.create_playlist(
                    access_token, name, description, public=True
                )
                await client.add_tracks(access_token, playlist_id, matched_uris)
                db.add(
                    SpotifyRoundPlaylist(
                        round_id=round_id, user_id=account_id, playlist_id=playlist_id
                    )
                )
                await db.commit()
        except SpotifyAuthError as exc:
            # Single point of failure (MYS-169): a revoked grant on the shared
            # account breaks generation platform-wide until an admin reconnects
            # it. The caller can't fix this themselves, so log loudly here.
            logger.exception(
                "spotify playlist: shared account %s authorization rejected", account_id
            )
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
        playlist_url=playlist_url,
        track_count=len(matched_uris),
        total_count=len(submissions),
        unmatched=unmatched,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _get_connection(db: AsyncSession, user_id: uuid.UUID) -> SpotifyConnection | None:
    return await db.scalar(select(SpotifyConnection).where(SpotifyConnection.user_id == user_id))


async def _upsert_connection(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    spotify_user_id: str,
    refresh_token: str,
    scope: str | None,
) -> None:
    connection = await _get_connection(db, user_id)
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


async def _playlist_account_access_token(
    client: SpotifyClient, db: AsyncSession, connection: SpotifyConnection
) -> str:
    """Mint a fresh access token for the shared playlist account from its stored
    refresh token, persisting a rotated refresh token if Spotify returns one.

    MYS-169: failures here are an ops problem (the shared account, not the
    calling member, needs reconnecting), so they're logged loudly and mapped to
    a 503 rather than a per-user "reconnect" prompt."""
    try:
        refresh_token = decrypt_refresh_token(connection.refresh_token_encrypted)
    except SpotifyTokenCryptoError as exc:
        logger.exception("spotify playlist: shared account refresh token failed to decrypt")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists are temporarily unavailable — try again later",
        ) from exc

    try:
        tokens = await client.refresh_access_token(refresh_token)
    except SpotifyAuthError as exc:
        logger.exception("spotify playlist: shared account refresh token rejected")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="spotify playlists are temporarily unavailable — try again later",
        ) from exc
    except SpotifyApiError as exc:
        logger.exception("spotify playlist: couldn't reach spotify to refresh the shared token")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="couldn't reach spotify — try again",
        ) from exc

    if tokens.refresh_token and tokens.refresh_token != refresh_token:
        connection.refresh_token_encrypted = encrypt_refresh_token(tokens.refresh_token)
        await db.commit()

    return tokens.access_token
