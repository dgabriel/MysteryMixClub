"""Song search & resolution endpoints (MYS-44).

Two endpoints back the home-screen Song Search card:

* ``POST /api/v1/songs/resolve`` — paste a link, get the canonical cross-platform song
* ``GET  /api/v1/songs/search``  — search Deezer by title (+ optional artist)

Both are authenticated. All upstream knowledge lives in the service layer
(:mod:`app.services.odesli`, :mod:`app.services.deezer_search`); this router only
maps the services' typed errors onto HTTP status codes. Search uses Deezer
(keyless, free) and selection resolves the chosen track's URL via Odesli.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

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

router = APIRouter(prefix="/songs", tags=["songs"])


class ResolveRequest(BaseModel):
    url: str


@router.post("/resolve", response_model=ResolvedSong)
async def resolve_song(
    payload: ResolveRequest,
    _user: User = Depends(get_current_user),
    odesli: OdesliClient = Depends(get_odesli_client),
) -> ResolvedSong:
    try:
        return await odesli.resolve(payload.url)
    except InvalidSongURLError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SongNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="song not found") from exc
    except OdesliRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limited, try again shortly"
        ) from exc
    except OdesliTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="song lookup timed out"
        ) from exc
    except OdesliUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="song lookup is unavailable"
        ) from exc


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
