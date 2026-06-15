"""Song search & resolution endpoints (MYS-44).

Two endpoints back the home-screen Song Search card:

* ``POST /api/v1/songs/resolve`` — paste a link, get the canonical cross-platform song
* ``GET  /api/v1/songs/search``  — search Deezer by title (+ optional artist)

Both are authenticated. Search uses Deezer (keyless). Resolve assembles
cross-service links keyless (:mod:`app.services.song_links`); a *pasted* URL is
first turned into a song identity via :mod:`app.services.odesli` (keyless
identity only — not its link resolution). This router only maps service errors
onto HTTP status codes.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator

from app.auth.deps import get_current_user
from app.models.user import User
from app.services.deezer_search import (
    DeezerError,
    DeezerRateLimitError,
    DeezerSearchClient,
    DeezerTimeoutError,
    DeezerUnavailableError,
    SongSearchResult,
    get_deezer_client,
)
from app.services.odesli import (
    InvalidSongURLError,
    OdesliClient,
    OdesliRateLimitError,
    OdesliTimeoutError,
    OdesliUnavailableError,
    ResolvedSong,
    SongNotFoundError,
    get_odesli_client,
)
from app.services.song_links import SongLinkAssembler, get_link_assembler

router = APIRouter(prefix="/songs", tags=["songs"])


class ResolveRequest(BaseModel):
    # Either a pasted platform URL, or a known song identity (from a search
    # result). Identity is preferred — it skips the URL-identification step.
    url: str | None = None
    title: str | None = None
    artist: str | None = None
    isrc: str | None = None
    album: str | None = None
    thumbnail_url: str | None = None

    @model_validator(mode="after")
    def _need_url_or_title(self) -> "ResolveRequest":
        if not (self.url and self.url.strip()) and not (self.title and self.title.strip()):
            raise ValueError("provide either a url or a title")
        return self


@router.post("/resolve", response_model=ResolvedSong)
async def resolve_song(
    payload: ResolveRequest,
    _user: User = Depends(get_current_user),
    odesli: OdesliClient = Depends(get_odesli_client),
    assembler: SongLinkAssembler = Depends(get_link_assembler),
) -> ResolvedSong:
    if payload.title:
        title, artist, isrc = payload.title, payload.artist, payload.isrc
        album, thumbnail_url = payload.album, payload.thumbnail_url
    else:
        # Paste flow: identify the song behind the URL (keyless Odesli identity).
        try:
            song = await odesli.resolve(payload.url or "")
        except InvalidSongURLError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except SongNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="song not found"
            ) from exc
        except OdesliRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limited, try again shortly",
            ) from exc
        except OdesliTimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="song lookup timed out"
            ) from exc
        except OdesliUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="song lookup is unavailable"
            ) from exc
        title, artist, isrc = song.title, song.artist, song.isrc
        album, thumbnail_url = song.album, song.thumbnail_url

    platforms = await assembler.assemble(title, artist, isrc)
    return ResolvedSong(
        title=title,
        artist=artist,
        album=album,
        thumbnail_url=thumbnail_url,
        isrc=isrc,
        platforms=platforms,
    )


@router.get("/search", response_model=SongSearchResult)
async def search_songs(
    q: str = Query(min_length=1, description="Song title to search for"),
    artist: str | None = Query(default=None, description="Optional artist to narrow results"),
    _user: User = Depends(get_current_user),
    deezer: DeezerSearchClient = Depends(get_deezer_client),
) -> SongSearchResult:
    try:
        return await deezer.search(q, artist)
    except DeezerRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limited, try again shortly"
        ) from exc
    except DeezerTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="search timed out"
        ) from exc
    except DeezerUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="search is unavailable"
        ) from exc
    except DeezerError as exc:
        # Catch-all for input-level service errors (e.g. empty title).
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
