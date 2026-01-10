"""
Abstract base class for music search providers.
All music search implementations must inherit from this class.
"""
from abc import ABC, abstractmethod
from typing import Optional


class MusicSearchProvider(ABC):
    """
    Abstract base class for music search providers.

    To add a new provider:
    1. Create a new file in this directory (e.g., spotify.py)
    2. Inherit from this class
    3. Implement the search_track method
    4. Update the provider factory in music_service.py
    """

    @abstractmethod
    async def search_track(self, artist: str, title: str, album: Optional[str] = None) -> dict:
        """
        Search for a track by artist and title.

        Args:
            artist: The artist name
            title: The song/track title
            album: Optional album name for more accurate results

        Returns:
            dict: A dictionary containing:
                - track_url: Direct URL to the track on this platform
                - track_name: Official track name
                - artist_name: Official artist name
                - album_name: Album name (if available)
                - artwork_url: High-resolution album artwork URL (if available)

        Raises:
            ValueError: If the track cannot be found
            Exception: For any API errors
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Return the name of this provider (e.g., 'iTunes', 'Spotify').
        Used for logging and debugging.
        """
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """
        Return True if this provider requires an API key.
        Used to validate configuration at startup.
        """
        pass
