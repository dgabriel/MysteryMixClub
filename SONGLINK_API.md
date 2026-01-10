# song.link API Postman Collection

## Overview

This Postman collection allows you to test the song.link (Odesli) API, which provides universal music links that work across all streaming platforms.

## How to Use

### 1. Import the Collection

1. Open Postman
2. Click **Import** in the top left
3. Select the file: `songlink-api.postman_collection.json`
4. The collection will appear in your Collections sidebar

### 2. Explore the Requests

The collection is organized into two folders:

#### **Get Song Links**
- Lookup by Spotify URL
- Lookup by Apple Music URL
- Lookup by YouTube URL
- Lookup by Tidal URL
- Lookup with Invalid URL (error case)

#### **Test Different Platforms**
- Deezer URL
- Amazon Music URL
- YouTube Music URL

### 3. Run a Request

1. Select any request from the collection
2. Click the **Send** button
3. View the response in the bottom panel

### 4. Try Your Own URLs

To test with your own music URLs:

1. Find a song on any streaming platform
2. Copy the URL (e.g., `https://open.spotify.com/track/...`)
3. Open any request in the collection
4. Replace the `url` query parameter with your URL
5. Click **Send**

## API Response Structure

The song.link API returns:

```json
{
  "pageUrl": "https://song.link/...",  // Universal link
  "linksByPlatform": {
    "spotify": { "url": "..." },
    "appleMusic": { "url": "..." },
    "youtube": { "url": "..." },
    "amazonMusic": { "url": "..." },
    "tidal": { "url": "..." },
    "youtubeMusic": { "url": "..." },
    "deezer": { "url": "..." }
  },
  "entitiesByUniqueId": {
    "SONG_ID": {
      "title": "Song Title",
      "artistName": "Artist Name",
      "thumbnailUrl": "https://...",
      "apiProvider": "spotify"
    }
  }
}
```

## Automated Tests

The collection includes automated tests that run after each request:

- ✅ Status code is 200
- ✅ Response has pageUrl
- ✅ Response has linksByPlatform
- ✅ Response has entitiesByUniqueId

View test results in the **Test Results** tab after sending a request.

## Supported Platforms

song.link supports URLs from:

- Spotify
- Apple Music
- YouTube
- YouTube Music
- Amazon Music
- Tidal
- Deezer
- Pandora
- SoundCloud
- And many more...

## Rate Limits

The song.link API is free but rate-limited:
- **100 requests per day** for the free tier
- Consider caching results to minimize API calls

## API Documentation

Official docs: https://www.notion.so/Odesli-API-a0ede3b5b636441f96a87ad5ad634c3f

## Example Use Cases

### 1. Get All Links for a Song

```
GET https://api.song.link/v1-alpha.1/links?url=https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp
```

### 2. Convert Spotify Link to Apple Music

Paste a Spotify URL and get the Apple Music link from `linksByPlatform.appleMusic.url`

### 3. Get Song Metadata

Extract title, artist, and artwork from `entitiesByUniqueId`

## Troubleshooting

### 400 Bad Request
- Check that the URL is a valid track/album URL
- Search URLs don't work (e.g., `https://open.spotify.com/search/...`)

### 404 Not Found
- The track might not be available on song.link
- Try a different streaming platform URL

### Rate Limit Exceeded
- Wait 24 hours or implement caching
- Consider the premium tier for higher limits

## Variables

The collection uses a variable:

- `{{baseUrl}}` = `https://api.song.link/v1-alpha.1`

You can modify this in Collection > Variables if needed.
