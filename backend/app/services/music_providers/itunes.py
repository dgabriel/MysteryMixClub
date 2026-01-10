"""
iTunes Search API provider.
Free API with no key required, generous rate limits.
"""
import httpx
from typing import Optional
from .base import MusicSearchProvider


class ITunesSearchProvider(MusicSearchProvider):
    """
    Music search provider using Apple's iTunes Search API.

    Advantages:
    - Free, no API key required
    - Generous rate limits (no hard limit documented)
    - Returns high-quality metadata
    - Works with song.link for cross-platform links

    Documentation: https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/
    """

    BASE_URL = "https://itunes.apple.com/search"

    @property
    def provider_name(self) -> str:
        return "iTunes"

    @property
    def requires_api_key(self) -> bool:
        return False

    async def search_track(self, artist: str, title: str, album: Optional[str] = None) -> dict:
        """
        Search for a track using iTunes Search API.

        Args:
            artist: The artist name
            title: The song/track title
            album: Optional album name (not used in current implementation)

        Returns:
            dict: Track metadata including Apple Music URL

        Raises:
            ValueError: If track is not found
            Exception: For API errors
        """
        search_query = f"{artist} {title}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    self.BASE_URL,
                    params={
                        "term": search_query,
                        "entity": "song",
                        "limit": 1,  # We only need the top result
                        "media": "music"
                    }
                )
                response.raise_for_status()
                data = response.json()

                # Check if we got results
                if not data.get("results") or len(data["results"]) == 0:
                    raise ValueError(f"Track not found: {artist} - {title}")

                # Extract the first result
                track = data["results"][0]

                # Get high-resolution artwork (upgrade from 100x100 to 600x600)
                artwork_url = track.get("artworkUrl100", "")
                if artwork_url:
                    artwork_url = artwork_url.replace("100x100", "600x600")

                return {
                    "track_url": track.get("trackViewUrl"),
                    "track_name": track.get("trackName"),
                    "artist_name": track.get("artistName"),
                    "album_name": track.get("collectionName"),
                    "artwork_url": artwork_url
                }

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ValueError(f"Track not found: {artist} - {title}")
                raise Exception(f"iTunes API error: {str(e)}")

            except httpx.RequestError as e:
                raise Exception(f"Error connecting to iTunes API: {str(e)}")
