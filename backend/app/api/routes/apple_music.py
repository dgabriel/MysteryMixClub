"""Apple Music routes — developer token + per-player mix playlists (MYS-108).

Three endpoints:

* ``GET /apple-music/developer-token`` — MusicKit JS needs the developer token in
  the browser to run the sign-in popup. This token identifies *the app*, not a
  user, and Apple's own web embeds ship it client-side, so exposing it to an
  authenticated caller is by design — unlike the ``.p8`` private key, which never
  leaves the server.
* ``GET  /mixes/{id}/apple-playlist`` — the caller's own playlist for a mix.
* ``POST /mixes/{id}/apple-playlist`` — generate it, using a Music User Token
  supplied per request and never stored.

Every playlist here is personal: MYS-107 established that Apple library playlists
cannot be made public, so these links open only for their owner.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field

from app.api.wire import WireModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import _load_club_as_member
from app.api.routes.mixes import _load_mix
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.apple_music_client import (
    LIBRARY_URL,
    AppleMusicApiError,
    AppleMusicAuthError,
    AppleMusicClient,
    get_apple_music_client,
)
from app.services.apple_music_token import AppleMusicTokenError
from app.services.apple_playlist_generation import (
    generate_mix_playlist,
    get_existing_playlist,
)

router = APIRouter(tags=["apple-music"])


class DeveloperTokenResponse(WireModel):
    token: str | None = None


class ApplePlaylistLinkResponse(WireModel):
    # Apple Music's Library, not the playlist — iOS can't deep-link to a library
    # playlist (MYS-190). playlist_name is how the member finds it. The name is
    # null for rows created before MYS-190 started recording it.
    playlist_url: str | None = None
    playlist_name: str | None = None


class UnmatchedTrack(WireModel):
    submission_id: uuid.UUID
    title: str
    artist: str
    # Why it was skipped (MYS-201): "source_only" — a Bandcamp/YouTube track with
    # no ISRC that can never match Apple's catalog — vs "no_catalog_match", an
    # ISRC-backed track Apple's storefront just doesn't carry. Lets the gap
    # summary say why rather than only how many.
    reason: Literal["source_only", "no_catalog_match"]
    # For a "source_only" track, the Bandcamp/YouTube page to link out to
    # (MYS-201); both None for "no_catalog_match" (it has an ISRC, no source_key).
    source: Literal["youtube", "bandcamp"] | None = None
    source_url: str | None = None


class GeneratePlaylistRequest(WireModel):
    music_user_token: str = Field(min_length=1, max_length=4096)
    # Minutes to add to UTC for the caller's local time, so a rebuilt playlist's
    # "[revised on HH:MM]" reads in their own clock. Bounded to real-world
    # offsets (UTC-12 .. UTC+14). Omitted → UTC.
    tz_offset_minutes: int | None = Field(default=None, ge=-720, le=840)


class GeneratePlaylistResponse(WireModel):
    playlist_url: str
    playlist_name: str
    track_count: int
    total_count: int
    unmatched: list[UnmatchedTrack] = []


@router.get("/apple-music/developer-token", response_model=DeveloperTokenResponse)
async def get_developer_token(
    current_user: User = Depends(get_current_user),  # auth gate only
    client: AppleMusicClient = Depends(get_apple_music_client),
) -> DeveloperTokenResponse:
    """The developer token for MusicKit JS, or null when Apple isn't configured.

    Null rather than an error: an unconfigured deployment is a normal state, and
    the client simply hides the Apple option.
    """
    if not client.is_configured:
        return DeveloperTokenResponse(token=None)
    try:
        return DeveloperTokenResponse(token=await client.developer_token())
    except AppleMusicTokenError:
        # Configured but unsignable (malformed key, mid-rotation) — same quiet
        # "unavailable" as unconfigured rather than a 500 on the round page.
        return DeveloperTokenResponse(token=None)


@router.get("/mixes/{round_id}/apple-playlist", response_model=ApplePlaylistLinkResponse)
async def get_mix_apple_playlist(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApplePlaylistLinkResponse:
    """The caller's own Apple playlist link for this mix, or null.

    Scoped to the caller by construction — one member never sees another's
    playlist, and the link wouldn't open for them anyway.
    """
    mix_ = await _load_mix(round_id, db)
    await _load_club_as_member(mix_.club_id, current_user, db)

    stored = await get_existing_playlist(db, round_id, current_user.id)
    if stored is None:
        return ApplePlaylistLinkResponse(playlist_url=None)
    return ApplePlaylistLinkResponse(playlist_url=LIBRARY_URL, playlist_name=stored.playlist_name)


@router.post("/mixes/{round_id}/apple-playlist", response_model=GeneratePlaylistResponse)
async def create_mix_apple_playlist(
    round_id: uuid.UUID,
    payload: GeneratePlaylistRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    client: AppleMusicClient = Depends(get_apple_music_client),
) -> GeneratePlaylistResponse:
    """Generate this mix's playlist in the caller's Apple Music library."""
    if not client.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="apple music is not configured",
        )
    mix_ = await _load_mix(round_id, db)
    club = await _load_club_as_member(mix_.club_id, current_user, db)

    try:
        result = await generate_mix_playlist(
            round_id,
            mix_,
            club,
            current_user.id,
            payload.music_user_token,
            db,
            client,
            tz_offset_minutes=payload.tz_offset_minutes,
        )
    except AppleMusicAuthError as exc:
        # 401 so the client re-runs the MusicKit popup rather than showing a dead
        # end — an expired/revoked MUT is the one failure the user can fix.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="apple music authorization expired — reconnect and try again",
        ) from exc
    except AppleMusicApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="apple music request failed"
        ) from exc

    return GeneratePlaylistResponse(
        playlist_url=result.playlist_url,
        playlist_name=result.playlist_name,
        track_count=result.track_count,
        total_count=result.total_count,
        unmatched=[
            UnmatchedTrack(
                submission_id=u.submission_id,
                title=u.title,
                artist=u.artist,
                reason=u.reason,
                source=u.source,
                source_url=u.source_url,
            )
            for u in result.unmatched
        ],
    )
