"""Song search & resolution endpoints (MYS-44).

Two endpoints back the home-screen Song Search card:

* ``POST /api/v1/songs/resolve`` — paste a link, get the canonical cross-platform song
* ``GET  /api/v1/songs/search``  — search Deezer by title (+ optional artist)

Both are authenticated. Search uses Deezer (keyless). Resolve assembles
cross-service links keyless (:mod:`app.services.song_links`); a *pasted* URL is
first turned into a song identity via :mod:`app.services.link_resolver` (keyless
identity only — not its link resolution). This router only maps service errors
onto HTTP status codes.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import StringConstraints, model_validator

from app.api.wire import WireModel

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
from app.services.link_resolver import (
    InvalidSongURLError,
    LinkResolver,
    ResolvedSong,
    ResolverRateLimitError,
    ResolverTimeoutError,
    ResolverUnavailableError,
    SongNotFoundError,
    get_link_resolver,
)
from app.services.song_links import (
    SongLinkAssembler,
    assemble_source_links,
    get_link_assembler,
)

router = APIRouter(prefix="/songs", tags=["songs"])

# Bound user-supplied free-text inputs (MYS-49). Length-bound everything; trim
# human text, leave URLs untrimmed. Submission persistence re-validates these on
# POST /submissions — this hardens the search/resolve surface itself.
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Isrc = Annotated[str, StringConstraints(strip_whitespace=True, max_length=32)]
Url = Annotated[str, StringConstraints(max_length=2048)]


class ResolveRequest(WireModel):
    # Either a pasted platform URL, or a known song identity (from a search
    # result). Identity is preferred — it skips the URL-identification step.
    url: Url | None = None
    title: ShortText | None = None
    artist: ShortText | None = None
    isrc: Isrc | None = None
    album: ShortText | None = None
    thumbnail_url: Url | None = None
    # Opt-in to source-only results (MYS-201). Off by default, so existing clients
    # get byte-identical behavior: a Bandcamp/YouTube link with no catalog ISRC
    # still resolves to a 404. When on, that link resolves to a source-only song.
    allow_source_only: bool = False

    @model_validator(mode="after")
    def _need_url_or_title(self) -> "ResolveRequest":
        if not (self.url and self.url.strip()) and not (self.title and self.title.strip()):
            raise ValueError("provide either a url or a title")
        return self


@router.post("/resolve", response_model=ResolvedSong)
async def resolve_song(
    payload: ResolveRequest,
    _user: User = Depends(get_current_user),
    resolver: LinkResolver = Depends(get_link_resolver),
    assembler: SongLinkAssembler = Depends(get_link_assembler),
) -> ResolvedSong:
    # Only ever set on a Bandcamp paste (both catalog-hit and source-only); the
    # frontend passes it back on submit so it persists for the embedded player.
    bandcamp_track_id: str | None = None
    if payload.title:
        title, artist, isrc = payload.title, payload.artist, payload.isrc
        album, thumbnail_url = payload.album, payload.thumbnail_url
    else:
        # Paste flow: identify the song behind the URL (keyless resolver).
        try:
            song = await resolver.resolve(payload.url or "")
        except InvalidSongURLError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except SongNotFoundError as exc:
            # A tagged exception (e.g. "bandcamp_custom_domain") carries an
            # accurate, user-facing reason worth surfacing; the ordinary "no
            # match" case stays a generic detail so it doesn't leak resolver
            # internals.
            detail = str(exc) if exc.code else "song not found"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        except ResolverRateLimitError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limited, try again shortly",
            ) from exc
        except ResolverTimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="song lookup timed out"
            ) from exc
        except ResolverUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="song lookup is unavailable"
            ) from exc
        if song.source is not None:
            # Source-only: no catalog ISRC (MYS-201). Off by default the link is
            # a miss, exactly as before; opt-in returns the source-only song.
            if not payload.allow_source_only:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="song not found")
            assert song.source_key is not None  # guaranteed alongside song.source
            platforms, _ = await assemble_source_links(
                assembler, song.title, song.artist, song.source_key
            )
            return ResolvedSong(
                title=song.title,
                artist=song.artist,
                album=song.album,
                thumbnail_url=song.thumbnail_url,
                isrc=None,
                source=song.source,
                source_key=song.source_key,
                source_url=song.source_url,
                bandcamp_track_id=song.bandcamp_track_id,
                platforms=platforms,
            )
        title, artist, isrc = song.title, song.artist, song.isrc
        album, thumbnail_url = song.album, song.thumbnail_url
        bandcamp_track_id = song.bandcamp_track_id

    platforms = await assembler.assemble(title, artist, isrc)
    return ResolvedSong(
        title=title,
        artist=artist,
        album=album,
        thumbnail_url=thumbnail_url,
        isrc=isrc,
        bandcamp_track_id=bandcamp_track_id,
        platforms=platforms,
    )


@router.get("/search", response_model=SongSearchResult)
async def search_songs(
    q: str = Query(min_length=1, max_length=200, description="Song title to search for"),
    artist: str | None = Query(
        default=None, max_length=200, description="Optional artist to narrow results"
    ),
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
