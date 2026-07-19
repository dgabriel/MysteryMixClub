"""Per-player Apple Music playlist generation for a round (MYS-108).

Mirrors the Spotify engine's shape (resolve → create → record), but the model is
fundamentally different: Spotify generates **one shared, public** playlist from a
single service account, whereas Apple library playlists cannot be made public
(MYS-107), so every player generates **their own copy into their own library**.

Consequences that show up below:
* keyed by (round, user), never a shared account id;
* the caller's Music User Token is passed in per call and never stored;
* the resulting link is personal — it opens only for its owner.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.apple_round_playlist import AppleRoundPlaylist
from app.models.league import League
from app.models.round import Round
from app.models.submission import Submission
from app.services.apple_music_client import LIBRARY_URL, AppleMusicClient
from app.services.spotify_playlist import playlist_description, playlist_name


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


@dataclass
class GeneratedApplePlaylist:
    # Apple Music's Library, not the playlist itself — iOS can't deep-link to a
    # library playlist (MYS-190). `playlist_name` is what lets the member find it.
    playlist_url: str
    playlist_name: str
    track_count: int
    total_count: int
    unmatched: list[UnmatchedSubmission] = field(default_factory=list)


async def get_existing_playlist(
    db: AsyncSession, round_id: uuid.UUID, user_id: uuid.UUID
) -> AppleRoundPlaylist | None:
    """The caller's *current* playlist for a round, or None.

    Superseded rows (the round was reopened for submission) are treated as
    absent, so the UI offers a rebuild — but they stay in the table so the
    rebuild knows to name itself as a revision.
    """
    return await db.scalar(
        select(AppleRoundPlaylist).where(
            AppleRoundPlaylist.round_id == round_id,
            AppleRoundPlaylist.user_id == user_id,
            AppleRoundPlaylist.superseded_at.is_(None),
        )
    )


async def _any_previous_playlist(
    db: AsyncSession, round_id: uuid.UUID, user_id: uuid.UUID
) -> AppleRoundPlaylist | None:
    """Any row for this (round, user), superseded or not."""
    return await db.scalar(
        select(AppleRoundPlaylist).where(
            AppleRoundPlaylist.round_id == round_id,
            AppleRoundPlaylist.user_id == user_id,
        )
    )


def revised_playlist_name(name: str, when: datetime, tz_offset_minutes: int | None) -> str:
    """Append a ``[revised on HH:MM]`` suffix to a rebuilt playlist's name.

    Apple accepts two identically-named playlists without complaint, which
    leaves the member's library ambiguous after a round is reopened. The time is
    rendered in the member's own timezone when the client sends its offset,
    since a UTC clock time on a personal playlist is worse than no clock time.
    """
    local = when + timedelta(minutes=tz_offset_minutes) if tz_offset_minutes is not None else when
    return f"{name} [revised on {local:%H:%M}]"


async def generate_round_playlist(
    round_id: uuid.UUID,
    round_: Round,
    league: League,
    user_id: uuid.UUID,
    music_user_token: str,
    db: AsyncSession,
    client: AppleMusicClient,
    tz_offset_minutes: int | None = None,
) -> GeneratedApplePlaylist:
    """Create this round's playlist in the caller's Apple Music library.

    Raises ``AppleMusicAuthError`` / ``AppleMusicApiError``; the route maps those
    to HTTP. Submissions that don't resolve to a catalog song are reported as
    ``unmatched`` rather than failing the whole playlist — with no ISRC there's
    nothing to match on (MYS-166), so partial playlists are an expected outcome.
    """
    submissions = list(await db.scalars(select(Submission).where(Submission.round_id == round_id)))
    # Same seeded shuffle as the Spotify/YouTube playlists so every service
    # presents the round in one identical order (MYS-151). Sort first for a
    # stable input — Postgres order without ORDER BY is not guaranteed.
    submissions.sort(key=lambda s: s.id)
    random.Random(round_id.int).shuffle(submissions)

    # Resolve against the caller's own storefront — Apple's catalog is regional.
    resolver = client.with_storefront(await client.storefront_for_user(music_user_token))

    track_ids: list[str] = []
    unmatched: list[UnmatchedSubmission] = []
    for s in submissions:
        # Source-only tracks (MYS-201) have no ISRC to match against Apple's
        # catalog — they go unmatched, an expected partial-playlist outcome.
        song_id = (
            await resolver.catalog_song_id_for_isrc(s.isrc, s.title, s.artist) if s.isrc else None
        )
        if song_id:
            track_ids.append(song_id)
        else:
            unmatched.append(
                UnmatchedSubmission(
                    submission_id=s.id,
                    title=s.title,
                    artist=s.artist,
                    reason="source_only" if not s.isrc else "no_catalog_match",
                )
            )

    name = playlist_name(league.name, round_.round_number, round_.theme)
    description = playlist_description(league.name, round_.round_number, round_.theme)

    # A prior row — superseded or current — means this is a rebuild, so name it
    # distinctly; Apple would otherwise leave two same-named playlists sitting
    # side by side in the member's library.
    previous = await _any_previous_playlist(db, round_id, user_id)
    if previous is not None:
        name = revised_playlist_name(name, datetime.now(timezone.utc), tz_offset_minutes)

    playlist_id = await client.create_library_playlist(
        music_user_token, name, description, track_ids
    )

    # Record it so the round page can surface the link on later visits. One row
    # per (round, user): the rebuild takes over the existing row and clears the
    # superseded mark, so the table tracks the live playlist, not a history.
    if previous is None:
        db.add(
            AppleRoundPlaylist(
                round_id=round_id,
                user_id=user_id,
                playlist_id=playlist_id,
                playlist_name=name,
            )
        )
    else:
        previous.playlist_id = playlist_id
        previous.playlist_name = name
        previous.superseded_at = None
    await db.commit()

    return GeneratedApplePlaylist(
        playlist_url=LIBRARY_URL,
        playlist_name=name,
        track_count=len(track_ids),
        total_count=len(submissions),
        unmatched=unmatched,
    )
