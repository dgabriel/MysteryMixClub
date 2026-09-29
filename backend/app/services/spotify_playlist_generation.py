"""Shared-account playlist generate/refresh engine (MYS-169, MYS-176).

Pulled out of ``app.api.routes.spotify`` so it can be called from a plain
(non-HTTP) context — the mix-state-transition code paths in
``app.api.routes.mixes`` and ``app.jobs.advance_mixes`` — without those
modules importing the route file (``spotify.py`` already imports from
``mixes.py`` for ``_load_mix``; the reverse import would be circular).

One entry point:

* :func:`generate_mix_playlist` — the core engine. Raises
  ``SpotifyTokenCryptoError`` / ``SpotifyAuthError`` / ``SpotifyApiError`` on
  failure; callers decide how to surface that (the HTTP route maps them to
  503/502).

As of MYS-258 / ADR 0006 (Slice 1), the only caller is
``app.jobs.playlist_worker``, which dequeues a job and resolves the shared
account itself (:func:`playlist_account_user_id` / :func:`get_shared_connection`
below) before calling this function — the same account-resolution/no-op-if-
unconfigured logic that used to live in a ``try_auto_generate_playlist``
wrapper here now lives in the worker, since generation runs entirely out of
the request/job path and there's no longer a synchronous caller for a wrapper
to shield from a Spotify hiccup.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from collections import Counter
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
    IsrcLookup,
    SpotifyApiError,
    SpotifyClient,
    SpotifyNotFoundError,
)
from app.services.source_tracks import Source, source_fields
from app.services.spotify_playlist import playlist_description, playlist_name
from app.services.spotify_token_crypto import decrypt_refresh_token, encrypt_refresh_token

logger = logging.getLogger("app.services.spotify_playlist_generation")


# Why a submission didn't make the generated playlist (MYS-201): a source-only
# track (no ISRC — Bandcamp/YouTube) can never match a catalog, versus an
# ISRC-backed track this catalog simply doesn't carry.
UnmatchedReason = Literal["source_only", "no_catalog_match"]

# A 429 gets one retry after the wait Spotify asked for, capped: this runs in the
# background worker, out of any request, so waiting a few seconds is cheap.
_MAX_RETRY_AFTER_SECONDS = 10.0
_DEFAULT_RETRY_AFTER_SECONDS = 1.0
# A run where at least this share of the uncached lookups ERRORED (as opposed to
# cleanly not matching) is a broken integration, not a catalog gap, and must not
# publish a truncated playlist as if it had succeeded.
_MAX_ERROR_SHARE = 0.5

# Indirection so tests can skip the real wait.
_sleep = asyncio.sleep


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


def _failure_label(result: IsrcLookup) -> str:
    """A short fixed label for aggregating failures, never containing user data."""
    return f"http-{result.status}" if result.status else (result.reason or "unknown")


async def _lookup_isrc(client: SpotifyClient, isrc: str, token: str) -> IsrcLookup:
    """One ISRC lookup, retried once after a 429 for the wait Spotify asked for."""
    result = await client.lookup_track_by_isrc(isrc, token)
    if result.status == 429:
        wait = min(
            result.retry_after if result.retry_after is not None else _DEFAULT_RETRY_AFTER_SECONDS,
            _MAX_RETRY_AFTER_SECONDS,
        )
        logger.warning("spotify rate limited an ISRC lookup; retrying once after %.1fs", wait)
        await _sleep(wait)
        result = await client.lookup_track_by_isrc(isrc, token)
    return result


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

    # Read from the ORM objects now. The best-effort cache commit below rolls back on
    # failure, which expires them, and touching an expired attribute in an async
    # session raises MissingGreenlet: the "never fail on the cache write" promise
    # only holds if nothing after it needs these.
    name = playlist_name(club.name, mix_.mix_number, mix_.theme)
    description = playlist_description(club.name, mix_.mix_number, mix_.theme)

    submissions = list(await db.scalars(select(Submission).where(Submission.mix_id == round_id)))
    # Same seeded shuffle as get_mix_playlist so Spotify and YouTube always agree (MYS-151).
    # Sort first for a stable input — Postgres order without ORDER BY is not guaranteed.
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    matched_uris: list[str] = []
    unmatched: list[UnmatchedSubmission] = []
    app_token = await client.app_access_token()
    cached_anything = False
    already_cached = hits = misses = errors = 0
    error_reasons: Counter[str] = Counter()
    rate_limited = False

    for s in submissions:
        uri = s.spotify_track_uri
        if uri:
            already_cached += 1
        elif s.isrc:
            # Source-only tracks (MYS-201) have no ISRC to search by, so they skip
            # this block and simply go unmatched, like any track Spotify lacks.
            if app_token is None or rate_limited:
                # No token, or Spotify is still throttling us after a retry: asking
                # again cannot help and would only deepen the throttle.
                errors += 1
                error_reasons["no-app-token" if app_token is None else "skipped-after-429"] += 1
            else:
                result = await _lookup_isrc(client, s.isrc, app_token)
                if result.outcome == "hit" and result.uri:
                    uri = result.uri
                    s.spotify_track_uri = uri
                    cached_anything = True
                    hits += 1
                elif result.outcome == "miss":
                    misses += 1
                else:
                    errors += 1
                    label = _failure_label(result)
                    if label not in error_reasons:
                        # First sighting of each distinct failure only; the summary
                        # below carries the counts, and this never names the track.
                        logger.warning("spotify ISRC lookup failed (%s)", label)
                    error_reasons[label] += 1
                    rate_limited = result.status == 429
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

    attempted = hits + misses + errors
    logger.info(
        "spotify playlist for mix %s: %d submissions, %d already cached, %d newly matched, "
        "%d not on spotify, %d lookup errors%s",
        round_id,
        len(submissions),
        already_cached,
        hits,
        misses,
        errors,
        f" ({', '.join(f'{k} x{v}' for k, v in error_reasons.most_common())})"
        if error_reasons
        else "",
    )

    # Best-effort: persist newly resolved URIs, but never fail on the cache write
    # — the playlist is built from the in-memory uris regardless. Done before the
    # error gate below so a failed run still keeps the progress it made and a
    # re-run only has to resolve the remainder.
    if cached_anything:
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning(
                "could not persist newly resolved spotify track URIs for mix %s",
                round_id,
                exc_info=True,
            )

    if attempted and errors >= attempted * _MAX_ERROR_SHARE:
        # Refuse before touching the playlist: replace_tracks on an existing one
        # would swap a good playlist for a truncated set. The job is recorded as
        # failed with this text, which GET /mixes/{id}/spotify-playlist surfaces.
        detail = ", ".join(f"{k} x{v}" for k, v in error_reasons.most_common())
        raise SpotifyApiError(
            f"spotify ISRC lookup failed for {errors} of {attempted} tracks ({detail})"
        )

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
