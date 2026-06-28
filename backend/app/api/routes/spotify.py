"""Spotify connect + per-round playlist creation (MYS-83).

Three surfaces:

* ``GET  /spotify/connect``  — (auth) start OAuth; returns the consent URL.
* ``GET  /spotify/callback`` — (no auth) Spotify redirects here; we exchange the
  code, store the encrypted refresh token, and bounce back to the SPA. The user
  identity rides in a signed ``state`` token (the callback has no bearer header).
* ``GET  /spotify/status``   — (auth) is this user connected / is the app configured.
* ``DELETE /spotify/connection`` — (auth) disconnect.
* ``POST /rounds/:id/spotify-playlist`` — (auth) resolve the round's submissions
  to Spotify track URIs and create a saved playlist in the user's library; returns
  the link plus any tracks we couldn't match (the "unmatched" escape hatch).

Token exchange/refresh is server-side; the client secret and refresh token never
reach the browser.
"""

from __future__ import annotations

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
        # User denied consent or Spotify returned an error.
        return _redirect(return_to, "error")

    try:
        tokens = await client.exchange_code(code)
        if not tokens.refresh_token:
            # Initial authorization must include a refresh token; without it we
            # can't mint future access tokens.
            return _redirect(return_to, "error")
        spotify_user_id = await client.get_current_user_id(tokens.access_token)
    except (SpotifyAuthError, SpotifyApiError):
        return _redirect(return_to, "error")

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client: SpotifyClient = Depends(get_spotify_client),
) -> StatusResponse:
    connection = await _get_connection(db, current_user.id)
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

    connection = await _get_connection(db, current_user.id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="connect your spotify account first",
        )

    access_token = await _user_access_token(client, db, connection)

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

    stored = await db.scalar(
        select(SpotifyRoundPlaylist).where(
            SpotifyRoundPlaylist.round_id == round_id,
            SpotifyRoundPlaylist.user_id == current_user.id,
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
                    # User deleted the playlist in Spotify; recreate and update stored ID.
                    playlist_id, playlist_url = await client.create_playlist(
                        access_token, name, description
                    )
                    await client.add_tracks(access_token, playlist_id, matched_uris)
                    stored.playlist_id = playlist_id
                    await db.commit()
            else:
                playlist_id, playlist_url = await client.create_playlist(
                    access_token, name, description
                )
                await client.add_tracks(access_token, playlist_id, matched_uris)
                db.add(
                    SpotifyRoundPlaylist(
                        round_id=round_id, user_id=current_user.id, playlist_id=playlist_id
                    )
                )
                await db.commit()
        except SpotifyAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="your spotify connection expired — reconnect and try again",
            ) from exc
        except SpotifyApiError as exc:
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


async def _user_access_token(
    client: SpotifyClient, db: AsyncSession, connection: SpotifyConnection
) -> str:
    """Mint a fresh user access token from the stored refresh token, persisting a
    rotated refresh token if Spotify returns one. Maps failures to a 409 so the
    UI prompts a reconnect."""
    try:
        refresh_token = decrypt_refresh_token(connection.refresh_token_encrypted)
    except SpotifyTokenCryptoError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="your spotify connection is invalid — reconnect and try again",
        ) from exc

    try:
        tokens = await client.refresh_access_token(refresh_token)
    except SpotifyAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="your spotify connection expired — reconnect and try again",
        ) from exc
    except SpotifyApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="couldn't reach spotify — try again",
        ) from exc

    if tokens.refresh_token and tokens.refresh_token != refresh_token:
        connection.refresh_token_encrypted = encrypt_refresh_token(tokens.refresh_token)
        await db.commit()

    return tokens.access_token
