"""Song submission endpoints (MYS-51).

Puts a song — picked via the search/resolve flow — into a round:

* ``POST /api/v1/rounds/:id/submissions``      — submit (or replace) your song
* ``GET  /api/v1/rounds/:id/submissions/mine`` — your submission for the round
* ``GET  /api/v1/rounds/:id/submissions``      — all submissions (after close only)

The canonical track fields (isrc/title/artist/album/art) come from the client's
prior search/resolve call; the server additionally assembles cross-service
platform links (keyless) and persists them as ``submissions.platform_links`` for
playlist/playback. The assembler always returns at least open-on-service deep
links, so a transient upstream hiccup never blocks the submission.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.leagues import _load_league_as_member
from app.api.routes.rounds import _load_round
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.league_member import LeagueMember
from app.models.submission import Submission
from app.models.user import User
from app.services.song_links import SongLinkAssembler, get_link_assembler
from app.services.youtube_resolver import YouTubeResolver, get_youtube_resolver

router = APIRouter(tags=["submissions"])

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Isrc = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=280)]
Album = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
AlbumArtUrl = Annotated[str, StringConstraints(max_length=2048)]


class SubmissionCreate(BaseModel):
    # Canonical identity + display fields from the search/resolve result. The
    # cross-service links are assembled server-side from title/artist/isrc.
    isrc: Isrc
    title: ShortText
    artist: ShortText
    album: Album | None = None
    album_art_url: AlbumArtUrl | None = None
    note: Note | None = None
    participation_mode: Literal["playing", "vibing"] | None = None


class SubmissionResponse(BaseModel):
    id: str
    round_id: str
    user_id: str
    isrc: str
    title: str
    artist: str
    album: str | None
    album_art_url: str | None
    note: str | None
    participation_mode: str
    created_at: datetime


def _to_response(s: Submission) -> SubmissionResponse:
    return SubmissionResponse(
        id=str(s.id),
        round_id=str(s.round_id),
        user_id=str(s.user_id),
        isrc=s.isrc,
        title=s.title,
        artist=s.artist,
        album=s.album,
        album_art_url=s.album_art_url,
        note=s.note,
        participation_mode=s.participation_mode,
        created_at=s.created_at,
    )


@router.post("/rounds/{round_id}/submissions", response_model=SubmissionResponse)
async def submit_song(
    round_id: uuid.UUID,
    payload: SubmissionCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    assembler: SongLinkAssembler = Depends(get_link_assembler),
    youtube: YouTubeResolver = Depends(get_youtube_resolver),
) -> SubmissionResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    if round_.state != "open_submission":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="this round is not accepting submissions"
        )

    # Assemble cross-service playback links keyless from the picked track. Always
    # returns at least deep links, so this never blocks the submission.
    platform_links = await assembler.assemble(payload.title, payload.artist, payload.isrc)
    # Resolve a concrete YouTube video id for the shared watch_videos playlist.
    # Best-effort: None on any failure, so it never blocks the submission.
    youtube_video_id = await youtube.video_id_for(payload.title, payload.artist)

    # Per-round mode: an explicit override wins; otherwise default from the
    # member's per-league vibe setting (MYS-112).
    member = await db.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == round_.league_id,
            LeagueMember.user_id == current_user.id,
            LeagueMember.removed_at.is_(None),
        )
    )
    member_default_vibe = member.vibe_mode if member is not None else False
    mode = payload.participation_mode or ("vibing" if member_default_vibe else "playing")

    existing = await db.scalar(
        select(Submission).where(
            Submission.round_id == round_id, Submission.user_id == current_user.id
        )
    )
    if existing is None:
        submission = Submission(
            round_id=round_id,
            user_id=current_user.id,
            isrc=payload.isrc,
            title=payload.title,
            artist=payload.artist,
            album=payload.album,
            album_art_url=payload.album_art_url,
            platform_links=platform_links,
            youtube_video_id=youtube_video_id,
            note=payload.note,
            participation_mode=mode,
        )
        db.add(submission)
        response.status_code = status.HTTP_201_CREATED
    else:
        # Replace in place while the round is open.
        existing.isrc = payload.isrc
        existing.title = payload.title
        existing.artist = payload.artist
        existing.album = payload.album
        existing.album_art_url = payload.album_art_url
        existing.platform_links = platform_links
        existing.youtube_video_id = youtube_video_id
        existing.note = payload.note
        existing.participation_mode = mode
        submission = existing

    await db.commit()
    await db.refresh(submission)
    return _to_response(submission)


@router.get("/rounds/{round_id}/submissions/mine", response_model=SubmissionResponse)
async def get_my_submission(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    submission = await db.scalar(
        select(Submission).where(
            Submission.round_id == round_id, Submission.user_id == current_user.id
        )
    )
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="you have not submitted to this round"
        )
    return _to_response(submission)


@router.get("/rounds/{round_id}/submissions", response_model=list[SubmissionResponse])
async def list_submissions(
    round_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionResponse]:
    round_ = await _load_round(round_id, db)
    await _load_league_as_member(round_.league_id, current_user, db)
    # Submissions stay private until the round closes (anonymity during voting).
    if round_.state != "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="submissions are revealed after the round closes",
        )
    submissions = await db.scalars(
        select(Submission)
        .where(Submission.round_id == round_id)
        .order_by(Submission.created_at.asc())
    )
    return [_to_response(s) for s in submissions]
