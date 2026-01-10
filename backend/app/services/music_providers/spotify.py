"""
Spotify Web API provider.
Requires API key (Client ID + Secret).

TO USE THIS PROVIDER:
1. Go to https://developer.spotify.com/dashboard
2. Create an app
3. Get Client ID and Client Secret
4. Set environment variables:
   - SPOTIFY_CLIENT_ID=your_client_id
   - SPOTIFY_CLIENT_SECRET=your_client_secret
5. Update config.py to set MUSIC_SEARCH_PROVIDER="spotify"
6. Uncomment the import in __init__.py
"""
import httpx
import base64
from typing import Optional
from .base import MusicSearchProvider


class SpotifySearchProvider(MusicSearchProvider):
    """
    Music search provider using Spotify Web API.

    Advantages:
    - Largest music catalog
    - Excellent search accuracy
    - Rich metadata
    - Works perfectly with song.link

    Disadvantages:
    - Requires API key (free but needs registration)
    - Rate limited (generous limits for non-commercial use)

    Documentation: https://developer.spotify.com/documentation/web-api
    """

    BASE_URL = "https://api.spotify.com/v1"
    AUTH_URL = "https://accounts.spotify.com/api/token"

    def __init__(self, client_id: str, client_secret: str):
        """
        Initialize the Spotify provider.

        Args:
            client_id: Spotify Client ID
            client_secret: Spotify Client Secret
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token = None

    @property
    def provider_name(self) -> str:
        return "Spotify"

    @property
    def requires_api_key(self) -> bool:
        return True

    async def _get_access_token(self) -> str:
        """
        Get an access token using Client Credentials flow.
        Tokens are cached and reused until they expire.
        """
        if self._access_token:
            # TODO: Add token expiration check
            return self._access_token

        # Encode credentials
        credentials = f"{self.client_id}:{self.client_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.AUTH_URL,
                headers={
                    "Authorization": f"Basic {encoded}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={"grant_type": "client_credentials"}
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            return self._access_token

    async def search_track(self, artist: str, title: str, album: Optional[str] = None) -> dict:
        """
        Search for a track using Spotify Web API.

        Args:
            artist: The artist name
            title: The song/track title
            album: Optional album name for more accurate results

        Returns:
            dict: Track metadata including Spotify URL

        Raises:
            ValueError: If track is not found
            Exception: For API errors
        """
        # Build search query
        query = f"artist:{artist} track:{title}"
        if album:
            query += f" album:{album}"

        # Get access token
        token = await self._get_access_token()

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/search",
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "q": query,
                        "type": "track",
                        "limit": 1
                    }
                )
                response.raise_for_status()
                data = response.json()

                # Check if we got results
                tracks = data.get("tracks", {}).get("items", [])
                if not tracks:
                    raise ValueError(f"Track not found: {artist} - {title}")

                # Extract the first result
                track = tracks[0]

                # Get highest quality artwork
                images = track["album"]["images"]
                artwork_url = images[0]["url"] if images else None

                return {
                    "track_url": track["external_urls"]["spotify"],
                    "track_name": track["name"],
                    "artist_name": track["artists"][0]["name"],
                    "album_name": track["album"]["name"],
                    "artwork_url": artwork_url
                }

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise ValueError(f"Track not found: {artist} - {title}")
                raise Exception(f"Spotify API error: {str(e)}")

            except httpx.RequestError as e:
                raise Exception(f"Error connecting to Spotify API: {str(e)}")
