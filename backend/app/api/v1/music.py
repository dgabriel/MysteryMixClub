from fastapi import APIRouter, HTTPException
from app.schemas.song import MusicSearchRequest, MusicSearchResponse
from app.services import music_service


router = APIRouter()


@router.post("/search", response_model=MusicSearchResponse)
async def search_song(request: MusicSearchRequest):
    """
    Search for a song using artist and title.
    Returns song.link universal link and streaming service URLs.
    """
    try:
        result = await music_service.search_song(
            artist=request.artist,
            title=request.title,
            album=request.album
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error searching for song: {str(e)}")


@router.get("/lookup", response_model=MusicSearchResponse)
async def lookup_song_by_url(url: str):
    """
    Lookup a song by its streaming service URL (Spotify, Apple Music, etc).
    Returns song.link universal link and all available streaming service URLs.
    """
    try:
        result = await music_service.get_song_by_url(url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error looking up song: {str(e)}")
