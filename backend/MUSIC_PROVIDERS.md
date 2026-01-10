# Music Search Providers

This application uses a **pluggable provider architecture** for music search. You can easily swap between different music APIs without changing any code.

## Current Provider

**Default**: iTunes Search API (free, no API key required)

## Available Providers

### 1. iTunes Search API (Active)

**Status**: ✅ Implemented and working

**Advantages**:
- Free, no API key required
- No rate limits (very generous)
- High-quality metadata
- Works perfectly with song.link

**Configuration**: None needed (default)

---

### 2. Spotify Web API (Ready to Use)

**Status**: ⚠️ Implemented but requires API key

**Advantages**:
- Largest music catalog
- Best search accuracy
- Rich metadata

**Disadvantages**:
- Requires free API key
- Rate limited (generous for non-commercial use)

**How to Enable**:

1. Get API credentials:
   - Go to https://developer.spotify.com/dashboard
   - Create an app (it's free)
   - Copy your Client ID and Client Secret

2. Update `.env`:
   ```bash
   MUSIC_SEARCH_PROVIDER=spotify
   SPOTIFY_CLIENT_ID=your_client_id_here
   SPOTIFY_CLIENT_SECRET=your_client_secret_here
   ```

3. Uncomment the Spotify import in `music_service.py`:
   ```python
   from app.services.music_providers import SpotifySearchProvider
   ```

4. Uncomment the Spotify provider code in `get_music_provider()` function

5. Restart the backend

---

### 3. Deezer API (Not Yet Implemented)

**Status**: 🚧 Not implemented

**To Implement**:
1. Create `backend/app/services/music_providers/deezer.py`
2. Inherit from `MusicSearchProvider`
3. Implement the `search_track()` method
4. Add to the factory in `music_service.py`

---

## How to Swap Providers

### Quick Method (Environment Variable)

Edit your `.env` file:

```bash
# Use iTunes (default, no key needed)
MUSIC_SEARCH_PROVIDER=itunes

# Use Spotify (requires API key)
MUSIC_SEARCH_PROVIDER=spotify
SPOTIFY_CLIENT_ID=your_id
SPOTIFY_CLIENT_SECRET=your_secret

# Use Deezer (when implemented)
MUSIC_SEARCH_PROVIDER=deezer
```

Then restart the backend:
```bash
docker compose restart backend
```

---

## How to Add a New Provider

Let's say you want to add **Last.fm API**:

### Step 1: Create the Provider Class

Create `backend/app/services/music_providers/lastfm.py`:

```python
from typing import Optional
from .base import MusicSearchProvider
import httpx

class LastFmSearchProvider(MusicSearchProvider):
    BASE_URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "Last.fm"

    @property
    def requires_api_key(self) -> bool:
        return True

    async def search_track(self, artist: str, title: str, album: Optional[str] = None) -> dict:
        """Search Last.fm API for a track"""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "method": "track.search",
                    "artist": artist,
                    "track": title,
                    "api_key": self.api_key,
                    "format": "json"
                }
            )
            data = response.json()

            # Parse Last.fm response
            track = data["results"]["trackmatches"]["track"][0]

            return {
                "track_url": track["url"],
                "track_name": track["name"],
                "artist_name": track["artist"],
                "album_name": None,  # Last.fm search doesn't return album
                "artwork_url": track.get("image", [{}])[-1].get("#text")
            }
```

### Step 2: Update Config

Add to `backend/app/config.py`:

```python
# Last.fm API (only needed if MUSIC_SEARCH_PROVIDER="lastfm")
LASTFM_API_KEY: str = ""
```

### Step 3: Update the Factory

In `backend/app/services/music_service.py`:

```python
from app.services.music_providers import LastFmSearchProvider

def get_music_provider() -> MusicSearchProvider:
    # ... existing code ...

    elif provider_name == "lastfm":
        if not settings.LASTFM_API_KEY:
            raise ValueError("Last.fm requires LASTFM_API_KEY")
        return LastFmSearchProvider(api_key=settings.LASTFM_API_KEY)
```

### Step 4: Use It

Update `.env`:
```bash
MUSIC_SEARCH_PROVIDER=lastfm
LASTFM_API_KEY=your_key_here
```

That's it! 🎉

---

## Provider Interface

All providers must implement:

```python
class MusicSearchProvider(ABC):
    @abstractmethod
    async def search_track(self, artist: str, title: str, album: Optional[str] = None) -> dict:
        """
        Returns:
            {
                "track_url": "https://...",      # Required
                "track_name": "Song Title",      # Required
                "artist_name": "Artist Name",    # Required
                "album_name": "Album Name",      # Optional
                "artwork_url": "https://..."     # Optional
            }
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return 'iTunes', 'Spotify', etc."""
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Return True if API key is needed"""
        pass
```

---

## Testing a New Provider

Test manually with curl:

```bash
curl -X POST http://localhost:8000/api/v1/music/search \
  -H "Content-Type: application/json" \
  -d '{"artist": "The Beatles", "title": "Hey Jude"}'
```

Check the response includes all required fields.

---

## Troubleshooting

### Provider Not Found Error

```
ValueError: Unknown music search provider: xyz
```

**Fix**: Check `.env` has valid `MUSIC_SEARCH_PROVIDER` (itunes, spotify, deezer)

### Missing API Key Error

```
ValueError: Spotify provider requires SPOTIFY_CLIENT_ID
```

**Fix**: Add the required credentials to `.env`

### Import Error

```
ImportError: cannot import name 'SpotifySearchProvider'
```

**Fix**: Uncomment the import in `music_service.py`

---

## Architecture Diagram

```
┌─────────────┐
│   Frontend  │
│  (React)    │
└──────┬──────┘
       │
       │ POST /api/v1/music/search
       │ {"artist": "...", "title": "..."}
       │
       ▼
┌──────────────────┐
│  music_service   │
│  (Factory)       │
└──────┬───────────┘
       │
       │ get_music_provider()
       │
       ▼
┌──────────────────────────────┐
│   MusicSearchProvider        │
│   (Interface)                │
└──────┬──────────┬────────────┘
       │          │
       ▼          ▼
  ┌────────┐  ┌─────────┐
  │ iTunes │  │ Spotify │
  │Provider│  │Provider │
  └────┬───┘  └────┬────┘
       │           │
       │ search_track()
       │
       ▼
  ┌──────────────┐
  │  Track URL   │
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │  song.link   │
  │  API         │
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ All Platform │
  │ Links        │
  └──────────────┘
```

---

## Benefits of This Architecture

1. **Easy to swap**: Change one line in `.env`
2. **Easy to extend**: Add new providers without modifying existing code
3. **Type safe**: Abstract base class ensures all providers have the same interface
4. **Testable**: Each provider can be tested independently
5. **No vendor lock-in**: Not tied to any single music API

---

## FAQ

**Q: Can I use multiple providers at once?**
A: Not currently, but you could modify the factory to try providers in fallback order.

**Q: Which provider is best?**
A: iTunes for simplicity (no key). Spotify for accuracy (if you have a key).

**Q: Does this cost money?**
A: All providers have free tiers sufficient for this use case.

**Q: What if a provider's API changes?**
A: Only update that provider's file. Other providers are unaffected.
