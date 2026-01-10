"""
Service for searching music tracks and fetching streaming links.

This service uses a pluggable provider architecture to support multiple
music search APIs (iTunes, Spotify, etc.). The provider can be easily
swapped by changing the MUSIC_SEARCH_PROVIDER config value.
"""
import httpx
from typing import Optional, Dict, Any
from app.schemas.song import MusicSearchResponse
from app.config import settings
from app.services.music_providers import ITunesSearchProvider, MusicSearchProvider
# from app.services.music_providers import SpotifySearchProvider  # Uncomment when ready to use


SONGLINK_API_URL = settings.SONGLINK_API_URL


def get_music_provider() -> MusicSearchProvider:
    """
    Factory function to get the configured music search provider.

    To add a new provider:
    1. Create a new provider class in music_providers/
    2. Add it to the imports above
    3. Add a case in this function
    4. Update MUSIC_SEARCH_PROVIDER in .env

    Returns:
        MusicSearchProvider: The configured provider instance

    Raises:
        ValueError: If the configured provider is invalid or missing credentials
    """
    provider_name = settings.MUSIC_SEARCH_PROVIDER.lower()

    if provider_name == "itunes":
        return ITunesSearchProvider()

    elif provider_name == "spotify":
        # Validate that Spotify credentials are configured
        if not settings.SPOTIFY_CLIENT_ID or not settings.SPOTIFY_CLIENT_SECRET:
            raise ValueError(
                "Spotify provider requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
                "environment variables. Please set them or use a different provider."
            )
        # Uncomment when SpotifySearchProvider is ready:
        # from app.services.music_providers.spotify import SpotifySearchProvider
        # return SpotifySearchProvider(
        #     client_id=settings.SPOTIFY_CLIENT_ID,
        #     client_secret=settings.SPOTIFY_CLIENT_SECRET
        # )
        raise ValueError(
            "Spotify provider is not yet implemented. "
            "Please use 'itunes' or implement SpotifySearchProvider."
        )

    elif provider_name == "deezer":
        raise ValueError(
            "Deezer provider is not yet implemented. "
            "Please use 'itunes' or implement DeezerSearchProvider."
        )

    else:
        raise ValueError(
            f"Unknown music search provider: {provider_name}. "
            f"Valid options: 'itunes', 'spotify', 'deezer'"
        )


async def search_song(artist: str, title: str, album: Optional[str] = None) -> MusicSearchResponse:
    """
    Search for a song using the configured music search provider,
    then get all platform links via song.link.

    This is the main entry point for song searching. It:
    1. Uses the configured provider to find the track
    2. Gets cross-platform links via song.link
    3. Combines the results into a unified response

    Args:
        artist: The artist name
        title: The song title
        album: Optional album name (not all providers use this)

    Returns:
        MusicSearchResponse with song.link URL and all streaming service links

    Raises:
        ValueError: If the song cannot be found
        Exception: For API errors
    """
    # Step 1: Get the music search provider
    provider = get_music_provider()

    # Step 2: Search for the track using the provider
    try:
        track_data = await provider.search_track(artist, title, album)
    except ValueError as e:
        # Re-raise ValueError as-is (track not found)
        raise
    except Exception as e:
        # Wrap other exceptions with provider context
        raise Exception(f"{provider.provider_name} search failed: {str(e)}")

    # Validate that we got a track URL
    track_url = track_data.get("track_url")
    if not track_url:
        raise ValueError(f"No track URL returned from {provider.provider_name}")

    # Step 3: Pass the track URL to song.link to get all platform links
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            songlink_response = await client.get(
                SONGLINK_API_URL,
                params={"url": track_url}
            )
            songlink_response.raise_for_status()
            songlink_data = songlink_response.json()

            # Step 4: Combine provider data with song.link data
            return _combine_provider_and_songlink_data(track_data, songlink_data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"song.link could not process URL: {track_url}")
            raise Exception(f"song.link API error: {str(e)}")

        except httpx.RequestError as e:
            raise Exception(f"Error connecting to song.link API: {str(e)}")


async def get_song_by_url(url: str) -> MusicSearchResponse:
    """
    Get song metadata from a direct streaming service URL.

    This bypasses the search provider and goes straight to song.link,
    which can handle URLs from any platform.

    Args:
        url: A URL from Spotify, Apple Music, YouTube, etc.

    Returns:
        MusicSearchResponse with song.link URL and streaming service links

    Raises:
        ValueError: If the URL is invalid or song cannot be found
        Exception: For API errors
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                SONGLINK_API_URL,
                params={"url": url}
            )
            response.raise_for_status()
            data = response.json()

            return _parse_songlink_only_response(data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise ValueError(f"Song not found for URL: {url}")
            raise Exception(f"song.link API error: {str(e)}")

        except httpx.RequestError as e:
            raise Exception(f"Error connecting to song.link API: {str(e)}")


def _combine_provider_and_songlink_data(
    provider_data: Dict[str, Any],
    songlink_data: Dict[str, Any]
) -> MusicSearchResponse:
    """
    Combine metadata from the search provider with links from song.link.

    We prefer the provider's metadata (more accurate) but use song.link for
    the cross-platform links.

    Args:
        provider_data: Data from the search provider (iTunes, Spotify, etc.)
        songlink_data: Data from song.link API

    Returns:
        MusicSearchResponse with combined data
    """
    # Get metadata from provider (more reliable)
    song_title = provider_data.get("track_name")
    artist_name = provider_data.get("artist_name")
    album_name = provider_data.get("album_name")
    artwork_url = provider_data.get("artwork_url")

    # Get the universal link from song.link
    songlink_url = songlink_data.get("pageUrl", "")

    # Extract platform-specific links from song.link
    links_by_platform = songlink_data.get("linksByPlatform", {})

    def get_platform_url(platform: str) -> Optional[str]:
        """Helper to safely extract platform URL"""
        platform_data = links_by_platform.get(platform, {})
        return platform_data.get("url")

    return MusicSearchResponse(
        songlink_url=songlink_url,
        song_title=song_title,
        artist_name=artist_name,
        album_name=album_name,
        artwork_url=artwork_url,
        spotify_url=get_platform_url("spotify"),
        apple_music_url=get_platform_url("appleMusic"),
        youtube_url=get_platform_url("youtube"),
        amazon_music_url=get_platform_url("amazon"),
        tidal_url=get_platform_url("tidal"),
        youtube_music_url=get_platform_url("youtubeMusic"),
        deezer_url=get_platform_url("deezer")
    )


def _parse_songlink_only_response(songlink_data: Dict[str, Any]) -> MusicSearchResponse:
    """
    Parse a song.link response when we don't have provider data.

    This is used for URL lookups where we go straight to song.link.

    Args:
        songlink_data: The JSON response from song.link API

    Returns:
        MusicSearchResponse with extracted data
    """
    # Get the universal link
    songlink_url = songlink_data.get("pageUrl", "")

    # Extract metadata if available
    entities = songlink_data.get("entitiesByUniqueId", {})

    song_title = None
    artist_name = None
    album_name = None
    artwork_url = None

    if entities:
        first_entity = next(iter(entities.values()), {})
        song_title = first_entity.get("title")
        artist_name = first_entity.get("artistName")
        artwork_url = first_entity.get("thumbnailUrl")

    # Extract platform-specific links
    links_by_platform = songlink_data.get("linksByPlatform", {})

    def get_platform_url(platform: str) -> Optional[str]:
        """Helper to safely extract platform URL"""
        platform_data = links_by_platform.get(platform, {})
        return platform_data.get("url")

    return MusicSearchResponse(
        songlink_url=songlink_url,
        song_title=song_title,
        artist_name=artist_name,
        album_name=album_name,
        artwork_url=artwork_url,
        spotify_url=get_platform_url("spotify"),
        apple_music_url=get_platform_url("appleMusic"),
        youtube_url=get_platform_url("youtube"),
        amazon_music_url=get_platform_url("amazon"),
        tidal_url=get_platform_url("tidal"),
        youtube_music_url=get_platform_url("youtubeMusic"),
        deezer_url=get_platform_url("deezer")
    )
