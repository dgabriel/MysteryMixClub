"""Apple Music API client for per-player library playlists (MYS-108).

Two-token auth, unlike Spotify: every call carries the server-minted **developer
token** (MYS-105), and any call touching a user's library additionally carries
that user's **Music User Token** (MUT), obtained client-side via MusicKit JS.

We deliberately do **not** persist the MUT. MusicKit JS caches it in the browser,
so the client sends it per request; storing it would add an encrypted-credential
surface for no functional gain, since the user is always present for these calls
(contrast the Spotify shared account, which must act unattended).

Playlists are per-player by necessity, not choice: MYS-107 established that an
API-created library playlist cannot be made public, so there is no shared link to
generate. See ``docs/discovery/spike-apple-music.md`` §4.1.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

import httpx

from app.services.apple_music_token import (
    AppleMusicTokenError,
    AppleMusicTokenService,
    get_apple_music_token_service,
)
from app.services.search_relevance import best_match

_API = "https://api.music.apple.com/v1"
CATALOG_SONGS_URL = _API + "/catalog/{storefront}/songs"
_LIBRARY_PLAYLISTS = _API + "/me/library/playlists"
_DEFAULT_TIMEOUT = 20.0
DEFAULT_STOREFRONT = "us"
# Apple caps tracks per add request; chunk rather than risk a rejected batch.
_TRACK_CHUNK = 100


class AppleMusicError(RuntimeError):
    """Base for Apple Music API failures."""


class AppleMusicAuthError(AppleMusicError):
    """The Music User Token was rejected — expired, revoked, or no subscription.

    Callers surface this as "reconnect", not a generic failure: it's the one
    error the user can actually fix, by re-running the MusicKit popup.
    """


class AppleMusicApiError(AppleMusicError):
    """Apple returned an unexpected status."""


def pick_catalog_song(
    title: str, artist: str | None, payload: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Choose the best song from a catalog ``filter[isrc]`` response.

    One ISRC routinely maps to several catalog songs (the same recording across
    album/EP/single), and duplicates can share an album name, so rank on
    title+artist rather than trusting Apple's ordering. Shared with the link
    assembler (MYS-106) so both paths pick the same recording.
    """
    if not payload:
        return None
    return best_match(
        title,
        artist,
        payload.get("data") or [],
        title_of=lambda item: (item.get("attributes") or {}).get("name") or "",
        artist_of=lambda item: (item.get("attributes") or {}).get("artistName"),
    )


# Apple Music's Library, as deep as any link can usefully go (MYS-190).
#
# iOS cannot deep-link to a library playlist: the Music app receives a
# /library/playlist/{id} URL, fails to resolve it, and shows "Item Not
# Available" even though the playlist is right there in the library (MYS-190).
# A link that dead-ends reads as "we failed to make your playlist", so mobile
# gets the Library root instead — which works in both the app and the web
# player — plus the playlist name so the member knows what to look for.
LIBRARY_URL = "https://music.apple.com/library"


def library_playlist_url(playlist_id: str) -> str:
    """Direct link to one library playlist — desktop only (MYS-214).

    The desktop *web player* resolves this path even though Apple doesn't
    document it as supported (it dead-ends in the native iOS app, MYS-190,
    which is why mobile uses :data:`LIBRARY_URL` instead). Undocumented
    behavior: if Apple changes this, desktop degrades to the same generic
    Library link mobile already uses, not a regression from today's baseline.
    """
    return f"https://music.apple.com/library/playlist/{playlist_id}"


class AppleMusicClient:
    """Calls the Apple Music API on behalf of one user.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a mock
    transport; production defaults to a real client with a timeout.
    """

    def __init__(
        self,
        token_service: AppleMusicTokenService,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        storefront: str = DEFAULT_STOREFRONT,
    ) -> None:
        self._tokens = token_service
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._storefront = storefront

    @property
    def is_configured(self) -> bool:
        return self._tokens.is_configured

    async def developer_token(self) -> str:
        """The app's developer token, for handing to MusicKit JS in the browser.

        Safe to expose to an authenticated client: it identifies the app, not a
        user, and Apple's own web embeds ship it client-side. The ``.p8`` key that
        signs it never leaves the server.
        """
        return await self._tokens.get_developer_token()

    def with_storefront(self, storefront: str) -> AppleMusicClient:
        """A copy pinned to ``storefront``, sharing this client's token service
        and transport. Catalog lookups are per-storefront, so resolution runs
        against the caller's region rather than the default."""
        return AppleMusicClient(
            self._tokens, client_factory=self._client_factory, storefront=storefront
        )

    async def _headers(self, music_user_token: str | None = None) -> dict[str, str]:
        try:
            developer_token = await self._tokens.get_developer_token()
        except AppleMusicTokenError as exc:
            raise AppleMusicApiError("apple music is not configured") from exc
        headers = {"Authorization": f"Bearer {developer_token}"}
        if music_user_token:
            headers["Music-User-Token"] = music_user_token
        return headers

    def _check(self, resp: httpx.Response) -> None:
        if resp.status_code in (401, 403):
            raise AppleMusicAuthError("apple music rejected the user token")
        if resp.status_code >= 400:
            raise AppleMusicApiError(f"apple music returned {resp.status_code}")

    async def catalog_song_id_for_isrc(
        self, isrc: str, title: str, artist: str | None
    ) -> str | None:
        """Catalog song id for an ISRC, or None when it doesn't resolve.

        Developer token only — no user auth. Best-effort: a lookup failure returns
        None so the track lands in "unmatched" rather than failing the playlist.
        """
        try:
            headers = await self._headers()
            async with self._client_factory() as client:
                resp = await client.get(
                    CATALOG_SONGS_URL.format(storefront=self._storefront),
                    params={"filter[isrc]": isrc},
                    headers=headers,
                )
            if resp.status_code != 200:
                return None
            chosen = pick_catalog_song(title, artist, resp.json())
        except (httpx.HTTPError, ValueError, AppleMusicApiError):
            return None
        return chosen.get("id") if chosen else None

    async def storefront_for_user(self, music_user_token: str) -> str:
        """The user's storefront, falling back to the default when unavailable.

        Apple's catalog is per-storefront, so a US-only lookup misses tracks for
        users in other regions (MYS-106 hardcodes `us`; this is the real value).
        """
        try:
            headers = await self._headers(music_user_token)
            async with self._client_factory() as client:
                resp = await client.get(f"{_API}/me/storefront", headers=headers)
            if resp.status_code != 200:
                return self._storefront
            data = resp.json().get("data") or []
            return data[0]["id"] if data else self._storefront
        except (httpx.HTTPError, ValueError, KeyError, IndexError, AppleMusicApiError):
            return self._storefront

    async def create_library_playlist(
        self,
        music_user_token: str,
        name: str,
        description: str,
        track_ids: list[str],
    ) -> str:
        """Create a playlist in the user's library and return its id.

        Sends the first chunk of tracks with the create call and appends the rest,
        since Apple's add endpoint is append-only (no reordering) — so chunk order
        is the final playlist order.
        """
        headers = await self._headers(music_user_token)
        head, rest = track_ids[:_TRACK_CHUNK], track_ids[_TRACK_CHUNK:]
        body: dict[str, Any] = {
            "attributes": {"name": name, "description": description},
            "relationships": {"tracks": {"data": [{"id": tid, "type": "songs"} for tid in head]}},
        }
        async with self._client_factory() as client:
            resp = await client.post(_LIBRARY_PLAYLISTS, json=body, headers=headers)
            self._check(resp)
            try:
                playlist_id = resp.json()["data"][0]["id"]
            except (ValueError, KeyError, IndexError) as exc:
                raise AppleMusicApiError("apple music returned an unreadable playlist") from exc

            for start in range(0, len(rest), _TRACK_CHUNK):
                chunk = rest[start : start + _TRACK_CHUNK]
                add = await client.post(
                    f"{_LIBRARY_PLAYLISTS}/{playlist_id}/tracks",
                    json={"data": [{"id": tid, "type": "songs"} for tid in chunk]},
                    headers=headers,
                )
                self._check(add)
        return playlist_id


@lru_cache
def get_apple_music_client() -> AppleMusicClient:
    """FastAPI dependency providing the Apple Music client."""
    return AppleMusicClient(get_apple_music_token_service())
