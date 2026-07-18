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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.apple_round_playlist import AppleRoundPlaylist
from app.models.league import League
from app.models.round import Round
from app.models.submission import Submission
from app.services.apple_music_client import AppleMusicClient, library_playlist_url
from app.services.spotify_playlist import playlist_description, playlist_name


@dataclass
class UnmatchedSubmission:
    submission_id: uuid.UUID
    title: str
    artist: str


@dataclass
class GeneratedApplePlaylist:
    playlist_url: str
    track_count: int
    total_count: int
    unmatched: list[UnmatchedSubmission] = field(default_factory=list)


async def get_existing_playlist(
    db: AsyncSession, round_id: uuid.UUID, user_id: uuid.UUID
) -> AppleRoundPlaylist | None:
    return await db.scalar(
        select(AppleRoundPlaylist).where(
            AppleRoundPlaylist.round_id == round_id,
            AppleRoundPlaylist.user_id == user_id,
        )
    )


async def generate_round_playlist(
    round_id: uuid.UUID,
    round_: Round,
    league: League,
    user_id: uuid.UUID,
    music_user_token: str,
    db: AsyncSession,
    client: AppleMusicClient,
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
        song_id = await resolver.catalog_song_id_for_isrc(s.isrc, s.title, s.artist)
        if song_id:
            track_ids.append(song_id)
        else:
            unmatched.append(
                UnmatchedSubmission(submission_id=s.id, title=s.title, artist=s.artist)
            )

    name = playlist_name(league.name, round_.round_number, round_.theme)
    description = playlist_description(league.name, round_.round_number, round_.theme)
    playlist_id = await client.create_library_playlist(
        music_user_token, name, description, track_ids
    )

    # Record it so the round page can surface the link on later visits. Apple has
    # no "replace tracks" for library playlists, so a repeat generation makes a
    # new playlist; the stored row points at the most recent one.
    stored = await get_existing_playlist(db, round_id, user_id)
    if stored is None:
        db.add(AppleRoundPlaylist(round_id=round_id, user_id=user_id, playlist_id=playlist_id))
    else:
        stored.playlist_id = playlist_id
    await db.commit()

    return GeneratedApplePlaylist(
        playlist_url=library_playlist_url(playlist_id),
        track_count=len(track_ids),
        total_count=len(submissions),
        unmatched=unmatched,
    )
