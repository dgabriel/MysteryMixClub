"""Shared-account playlist generate/refresh engine (MYS-169, MYS-176).

Pulled out of ``app.api.routes.spotify`` so it can be called from a plain
(non-HTTP) context — the mix-state-transition code paths in
``app.api.routes.mixes`` and ``app.jobs.advance_mixes`` — without those
modules importing the route file (``spotify.py`` already imports from
``mixes.py`` for ``_load_mix``; the reverse import would be circular).

Two entry points:

* :func:`generate_mix_playlist` — the core engine. Raises
  ``SpotifyTokenCryptoError`` / ``SpotifyAuthError`` / ``SpotifyApiError`` on
  failure; callers decide how to surface that (the HTTP route maps them to
  503/502, the auto-trigger below swallows them).
* :func:`try_auto_generate_playlist` — best-effort wrapper used when a mix
  enters ``open_voting`` (MYS-176): resolves the shared account, no-ops
  silently if it isn't configured/connected, and never raises — a Spotify
  hiccup must never block a mix from opening for voting.
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.club import Club
from app.models.mix import Mix
from app.models.spotify_connection import SpotifyConnection
from app.models.spotify_mix_playlist import SpotifyMixPlaylist
from app.models.submission import Submission
from app.services.spotify_client import (
    SpotifyApiError,
    SpotifyAuthError,
    SpotifyClient,
    SpotifyNotFoundError,
)
from app.services.source_tracks import Source, source_fields
from app.services.spotify_playlist import playlist_description, playlist_name
from app.services.spotify_token_crypto import (
    SpotifyTokenCryptoError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)

logger = logging.getLogger("app.services.spotify_playlist_generation")


# Why a submission didn't make the generated playlist (MYS-201): a source-only
# track (no ISRC — Bandcamp/YouTube) can never match a catalog, versus an
# ISRC-backed track this catalog simply doesn't carry.
UnmatchedReason = Literal["source_only", "no_catalog_match"]


@dataclass
class UnmatchedSubmission:
    submission_id: uuid.UUID
    title: str
    artist: str
    reason: UnmatchedReason
    # For a "source_only" entry, the Bandcamp/YouTube page it can be linked out to
    # (MYS-201); both None for a "no_catalog_match" entry, which has an ISRC rather
    # than a source_key.
    source: Source | None = None
    source_url: str | None = None


@dataclass
class GeneratedPlaylist:
    playlist_url: str | None
    track_count: int
    total_count: int
    unmatched: list[UnmatchedSubmission] = field(default_factory=list)


def playlist_account_user_id(settings: Settings) -> uuid.UUID | None:
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


async def get_shared_connection(db: AsyncSession, user_id: uuid.UUID) -> SpotifyConnection | None:
    return await db.scalar(select(SpotifyConnection).where(SpotifyConnection.user_id == user_id))


async def _playlist_account_access_token(
    client: SpotifyClient, db: AsyncSession, connection: SpotifyConnection
) -> str:
    """Mint a fresh access token for the shared playlist account from its stored
    refresh token, persisting a rotated refresh token if Spotify returns one.

    Raises ``SpotifyTokenCryptoError`` / ``SpotifyAuthError`` / ``SpotifyApiError``
    on failure — the caller (HTTP route or auto-trigger) decides how to surface
    that; this function has no HTTP concerns."""
    refresh_token = decrypt_refresh_token(connection.refresh_token_encrypted)
    tokens = await client.refresh_access_token(refresh_token)

    if tokens.refresh_token and tokens.refresh_token != refresh_token:
        connection.refresh_token_encrypted = encrypt_refresh_token(tokens.refresh_token)
        await db.commit()

    return tokens.access_token


async def generate_mix_playlist(
    round_id: uuid.UUID,
    mix_: Mix,
    club: Club,
    account_id: uuid.UUID,
    connection: SpotifyConnection,
    db: AsyncSession,
    client: SpotifyClient,
) -> GeneratedPlaylist:
    """Generate/refresh ``mix_``'s shared-account playlist.

    Raises ``SpotifyTokenCryptoError`` / ``SpotifyAuthError`` / ``SpotifyApiError``
    on failure. Does not raise ``HTTPException`` — this function has no HTTP
    concerns, so it's usable from a plain background/job context too."""
    access_token = await _playlist_account_access_token(client, db, connection)

    submissions = list(await db.scalars(select(Submission).where(Submission.mix_id == round_id)))
    # Same seeded shuffle as get_mix_playlist so Spotify and YouTube always agree (MYS-151).
    # Sort first for a stable input — Postgres order without ORDER BY is not guaranteed.
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    matched_uris: list[str] = []
    unmatched: list[UnmatchedSubmission] = []
    app_token = await client.app_access_token()
    cached_anything = False

    for s in submissions:
        uri = s.spotify_track_uri
        # Source-only tracks (MYS-201) have no ISRC to search by — they simply go
        # unmatched, like any other track Spotify's catalog doesn't carry.
        if not uri and app_token and s.isrc:
            uri = await client.search_track_uri_by_isrc(s.isrc, app_token)
            if uri:
                s.spotify_track_uri = uri
                cached_anything = True
        if uri:
            matched_uris.append(uri)
        else:
            source, source_url = source_fields(s.source_key)
            unmatched.append(
                UnmatchedSubmission(
                    submission_id=s.id,
                    title=s.title,
                    artist=s.artist,
                    reason="source_only" if not s.isrc else "no_catalog_match",
                    source=source,
                    source_url=source_url,
                )
            )

    # Best-effort: persist newly resolved URIs, but never fail on the cache write
    # — the playlist is built from the in-memory uris regardless.
    if cached_anything:
        try:
            await db.commit()
        except Exception:
            await db.rollback()

    name = playlist_name(club.name, mix_.mix_number, mix_.theme)
    description = playlist_description(club.name, mix_.mix_number, mix_.theme)

    # Keyed by (mix, shared account) — since the account is the same for every
    # caller, this is effectively one playlist per mix (MYS-169).
    stored = await db.scalar(
        select(SpotifyMixPlaylist).where(
            SpotifyMixPlaylist.mix_id == round_id,
            SpotifyMixPlaylist.user_id == account_id,
        )
    )

    playlist_url: str | None = None
    if matched_uris:
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
            db.add(SpotifyMixPlaylist(mix_id=round_id, user_id=account_id, playlist_id=playlist_id))
            await db.commit()

    return GeneratedPlaylist(
        playlist_url=playlist_url,
        track_count=len(matched_uris),
        total_count=len(submissions),
        unmatched=unmatched,
    )


async def try_auto_generate_playlist(
    round_id: uuid.UUID,
    mix_: Mix,
    club: Club,
    db: AsyncSession,
    client: SpotifyClient,
    settings: Settings,
) -> None:
    """Best-effort auto-generation when a mix opens for voting (MYS-176).

    No-ops silently if the shared account isn't configured/connected — this is
    a normal, expected state on any deployment that hasn't set up Spotify
    playlists, not an error. Never raises: a Spotify hiccup must never block
    the mix transition that triggered this."""
    account_id = playlist_account_user_id(settings)
    if account_id is None:
        return
    connection = await get_shared_connection(db, account_id)
    if connection is None:
        return
    try:
        await generate_mix_playlist(round_id, mix_, club, account_id, connection, db, client)
    except (SpotifyTokenCryptoError, SpotifyAuthError, SpotifyApiError):
        logger.exception("spotify playlist: automatic generation failed for mix %s", round_id)
