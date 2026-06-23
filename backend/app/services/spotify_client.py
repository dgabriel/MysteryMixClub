"""Spotify Web API client (MYS-83).

Owns every interaction with Spotify's auth and Web API surfaces so the rest of
the app sees only plain values (track URIs, a playlist URL) and typed errors.

Two token flows live here:

* **Client-credentials (app token)** — used only for *matching* a submission's
  ISRC to a Spotify track URI. No user involved; keyless-ish.
* **Authorization Code (per-user)** — used for *writes* (create playlist, add
  tracks) in the connecting user's own library. Token exchange and refresh are
  server-side; the client secret never leaves the backend.

Matching (:meth:`search_track_uri_by_isrc`) is best-effort and never raises —
an unconfigured app, a non-200, or no match all yield ``None`` so one bad track
can't sink a whole playlist. Writes raise :class:`SpotifyAuthError` (the user must
reconnect) or :class:`SpotifyApiError` (the call failed) so the route can react.

References:
  https://developer.spotify.com/documentation/web-api/tutorials/code-flow
  https://developer.spotify.com/documentation/web-api/reference/search
  https://developer.spotify.com/documentation/web-api/reference/create-playlist
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx

from app.config import Settings, get_settings

_ACCOUNTS_BASE = "https://accounts.spotify.com"
_AUTHORIZE_URL = f"{_ACCOUNTS_BASE}/authorize"
_TOKEN_URL = f"{_ACCOUNTS_BASE}/api/token"
_API_BASE = "https://api.spotify.com/v1"
_DEFAULT_TIMEOUT = 10.0

# Scopes needed to create/modify playlists AND to read the user's playlists
# (`playlist-read-private` — required to list them for the reuse lookup; without
# it GET /me/playlists returns 403 "Insufficient client scope").
PLAYLIST_SCOPES = (
    "playlist-read-private",
    "playlist-modify-public",
    "playlist-modify-private",
)

# Spotify caps tracks-per-add request at 100; chunk larger playlists.
_MAX_TRACKS_PER_ADD = 100
# Page size + cap for scanning the user's library for an existing playlist to
# reuse, so a huge library can't loop unbounded.
_PLAYLIST_PAGE_SIZE = 50
_MAX_PLAYLIST_PAGES = 10
# Refresh the app token a little before it actually expires to avoid races.
_APP_TOKEN_SKEW_SECONDS = 30


class SpotifyAuthError(RuntimeError):
    """The user's Spotify authorization is missing/expired — reconnect needed."""


class SpotifyApiError(RuntimeError):
    """A Spotify API call failed in a way the caller should surface."""


@dataclass(frozen=True)
class SpotifyTokens:
    """Tokens returned by an authorization-code exchange or refresh."""

    access_token: str
    # Spotify may omit a new refresh token on refresh; callers keep the old one.
    refresh_token: str | None
    scope: str | None
    expires_in: int


@dataclass(frozen=True)
class SpotifyTrack:
    """Exact track identity from the Spotify API (for the paste-a-link resolver)."""

    title: str
    artist: str | None
    album: str | None
    thumbnail_url: str | None
    isrc: str | None


class SpotifyClient:
    """Async wrapper over Spotify's auth + Web API.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a mock
    transport; in production it defaults to a real client with a timeout.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        redirect_uri: str = "",
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout = timeout
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._app_token: str | None = None
        self._app_token_expiry: float = 0.0
        self._app_token_lock = asyncio.Lock()

    @property
    def is_configured(self) -> bool:
        """True only when app credentials and a redirect URI are all present."""
        return bool(self._client_id and self._client_secret and self._redirect_uri)

    # ----------------------------------------------------------------- auth #

    def _basic_auth_header(self) -> dict[str, str]:
        raw = f"{self._client_id}:{self._client_secret}".encode("utf-8")
        return {"Authorization": f"Basic {base64.b64encode(raw).decode('ascii')}"}

    def authorize_url(self, state: str, scopes: tuple[str, ...] = PLAYLIST_SCOPES) -> str:
        """Build the Spotify consent URL to redirect the user to.

        ``state`` is an opaque anti-CSRF value the caller verifies on callback.
        """
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> SpotifyTokens:
        """Exchange an authorization ``code`` for tokens. Raises on failure."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        payload = await self._token_request(data)
        return SpotifyTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            scope=payload.get("scope"),
            expires_in=int(payload.get("expires_in", 0)),
        )

    async def refresh_access_token(self, refresh_token: str) -> SpotifyTokens:
        """Mint a fresh access token from a stored refresh token.

        Spotify occasionally rotates the refresh token; when it does, the new one
        is returned and the caller should persist it.
        """
        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        payload = await self._token_request(data)
        return SpotifyTokens(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            scope=payload.get("scope"),
            expires_in=int(payload.get("expires_in", 0)),
        )

    async def _token_request(self, data: dict[str, str]) -> dict:
        try:
            async with self._client_factory() as client:
                response = await client.post(
                    _TOKEN_URL, data=data, headers=self._basic_auth_header()
                )
        except httpx.HTTPError as exc:
            raise SpotifyApiError(f"spotify token request failed: {exc}") from exc

        if response.status_code in (400, 401):
            # invalid_grant / revoked consent — the user must reconnect.
            raise SpotifyAuthError("spotify authorization is invalid or expired")
        if response.status_code != 200:
            raise SpotifyApiError(f"spotify token request returned {response.status_code}")
        return response.json()

    async def app_access_token(self) -> str | None:
        """A cached client-credentials token for matching, or ``None`` if the app
        is unconfigured or the token request fails (matching is best-effort)."""
        if not self._client_id or not self._client_secret:
            return None
        now = time.monotonic()
        if self._app_token and now < self._app_token_expiry:
            return self._app_token
        async with self._app_token_lock:
            if self._app_token and time.monotonic() < self._app_token_expiry:
                return self._app_token
            try:
                payload = await self._token_request({"grant_type": "client_credentials"})
            except (SpotifyApiError, SpotifyAuthError):
                return None
            self._app_token = payload.get("access_token")
            self._app_token_expiry = time.monotonic() + max(
                0, int(payload.get("expires_in", 0)) - _APP_TOKEN_SKEW_SECONDS
            )
            return self._app_token

    # ----------------------------------------------------------- matching #

    async def search_track_uri_by_isrc(self, isrc: str, access_token: str) -> str | None:
        """Resolve an ISRC to a ``spotify:track:`` URI, or ``None``.

        Best-effort: any missing input, non-200, or empty result yields ``None``.
        """
        if not isrc or not access_token:
            return None
        params: dict[str, str | int] = {"q": f"isrc:{isrc}", "type": "track", "limit": 1}
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    f"{_API_BASE}/search",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            items = (response.json().get("tracks") or {}).get("items") or []
        except ValueError:
            return None
        if not items:
            return None
        uri = items[0].get("uri")
        return uri if isinstance(uri, str) and uri.startswith("spotify:track:") else None

    async def track_identity_by_id(self, track_id: str) -> SpotifyTrack | None:
        """Exact identity (title/artist/album/thumbnail/isrc) for a Spotify track
        id via the app token, or ``None`` (unconfigured / not found / error).

        Lets the paste-a-link resolver use precise Spotify metadata instead of a
        fuzzy title search, which can mis-match (MYS-100). Best-effort — never raises.
        """
        token = await self.app_access_token()
        if not token or not track_id:
            return None
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    f"{_API_BASE}/tracks/{track_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            data = response.json()
        except ValueError:
            return None
        name = data.get("name")
        if not isinstance(name, str) or not name:
            return None
        artist = ", ".join(a["name"] for a in data.get("artists") or [] if a.get("name")) or None
        album = data.get("album") or {}
        images = album.get("images") or []
        thumbnail = images[0].get("url") if images and isinstance(images[0], dict) else None
        isrc = (data.get("external_ids") or {}).get("isrc")
        return SpotifyTrack(
            title=name,
            artist=artist,
            album=album.get("name") or None,
            thumbnail_url=thumbnail,
            isrc=isrc or None,
        )

    # ------------------------------------------------------------- writes #

    async def get_current_user_id(self, access_token: str) -> str:
        """The authorized user's Spotify id (the playlist owner)."""
        data = await self._authed_get("/me", access_token)
        user_id = data.get("id")
        if not isinstance(user_id, str) or not user_id:
            raise SpotifyApiError("spotify /me returned no user id")
        return user_id

    async def create_playlist(
        self,
        access_token: str,
        name: str,
        description: str,
        *,
        public: bool = False,
    ) -> tuple[str, str]:
        """Create an empty playlist in the authorized user's library; return
        ``(playlist_id, external_url)``.

        Uses ``POST /me/playlists``. The older ``POST /users/{id}/playlists`` form
        was **retired in Spotify's February 2026 Web API changes** (it now returns
        403); ``/me/playlists`` creates the playlist for the token's own user.
        """
        body = {"name": name, "description": description, "public": public}
        data = await self._authed_post("/me/playlists", access_token, json=body)
        playlist_id = data.get("id")
        external_url = (data.get("external_urls") or {}).get("spotify")
        if not isinstance(playlist_id, str) or not playlist_id:
            raise SpotifyApiError("spotify create-playlist returned no id")
        return playlist_id, external_url or f"https://open.spotify.com/playlist/{playlist_id}"

    async def add_tracks(self, access_token: str, playlist_id: str, uris: list[str]) -> None:
        """Add track URIs to a playlist, chunked at Spotify's 100-per-call cap.

        Uses ``POST /playlists/{id}/items``; the ``/tracks`` form was retired in
        Spotify's February 2026 Web API changes.
        """
        for start in range(0, len(uris), _MAX_TRACKS_PER_ADD):
            chunk = uris[start : start + _MAX_TRACKS_PER_ADD]
            await self._authed_post(
                f"/playlists/{playlist_id}/items", access_token, json={"uris": chunk}
            )

    async def find_playlist_id_by_name(
        self, access_token: str, name: str, owner_id: str
    ) -> str | None:
        """Return the id of a playlist **owned by** ``owner_id`` whose name exactly
        matches ``name``, or ``None`` if no such playlist is found — so we can
        reuse it instead of creating a duplicate (MYS-87).

        ``GET /me/playlists`` lists both owned *and followed* playlists (and needs
        the ``playlist-read-private`` scope), so we only match ones the user owns
        (we can't write to a followed playlist).

        **Best-effort:** a rejected token raises :class:`SpotifyAuthError` (the
        caller prompts a reconnect), but any *other* failure — insufficient scope
        (an old token without ``playlist-read-private``), rate-limit, 5xx, network,
        bad JSON — degrades to ``None`` so the reuse lookup **never blocks
        generation**; at worst we create a fresh playlist. (A working create beats a
        502; robust reuse-by-id is MYS-89.) ``None`` also means the scan completed
        with no owned match.
        """
        offset = 0
        for _ in range(_MAX_PLAYLIST_PAGES):
            try:
                async with self._client_factory() as client:
                    response = await client.get(
                        f"{_API_BASE}/me/playlists",
                        params={"limit": _PLAYLIST_PAGE_SIZE, "offset": offset},
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
            except httpx.HTTPError:
                return None
            if response.status_code == 401:
                raise SpotifyAuthError("spotify access token rejected")
            if response.status_code != 200:
                return None
            try:
                payload = response.json()
            except ValueError:
                return None
            for playlist in payload.get("items") or []:
                if (
                    playlist.get("name") == name
                    and isinstance(playlist.get("id"), str)
                    and (playlist.get("owner") or {}).get("id") == owner_id
                ):
                    return playlist["id"]
            # `next` is Spotify's authoritative end-of-list cursor.
            if payload.get("next") is None:
                return None
            offset += _PLAYLIST_PAGE_SIZE
        return None

    async def replace_tracks(self, access_token: str, playlist_id: str, uris: list[str]) -> None:
        """Replace a playlist's contents with ``uris`` (idempotent regenerate).

        ``PUT /playlists/{id}/items`` sets the first 100; any remainder is
        appended via POST (same retired-endpoint-safe path as ``add_tracks``).
        """
        await self._authed_put(
            f"/playlists/{playlist_id}/items",
            access_token,
            json={"uris": uris[:_MAX_TRACKS_PER_ADD]},
        )
        rest = uris[_MAX_TRACKS_PER_ADD:]
        if rest:
            await self.add_tracks(access_token, playlist_id, rest)

    async def _authed_get(self, path: str, access_token: str) -> dict:
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    f"{_API_BASE}{path}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise SpotifyApiError(f"spotify GET {path} failed: {exc}") from exc
        return self._json_or_raise(response, path)

    async def _authed_post(self, path: str, access_token: str, *, json: dict) -> dict:
        try:
            async with self._client_factory() as client:
                response = await client.post(
                    f"{_API_BASE}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise SpotifyApiError(f"spotify POST {path} failed: {exc}") from exc
        return self._json_or_raise(response, path)

    async def _authed_put(self, path: str, access_token: str, *, json: dict) -> dict:
        try:
            async with self._client_factory() as client:
                response = await client.put(
                    f"{_API_BASE}{path}",
                    json=json,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise SpotifyApiError(f"spotify PUT {path} failed: {exc}") from exc
        return self._json_or_raise(response, path)

    @staticmethod
    def _json_or_raise(response: httpx.Response, path: str) -> dict:
        if response.status_code == 401:
            raise SpotifyAuthError("spotify access token rejected")
        if response.status_code not in (200, 201):
            raise SpotifyApiError(f"spotify {path} returned {response.status_code}")
        try:
            return response.json()
        except ValueError:
            return {}


def build_spotify_client(settings: Settings) -> SpotifyClient:
    return SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
        redirect_uri=settings.spotify_redirect_uri,
    )


@lru_cache
def get_spotify_client() -> SpotifyClient:
    """FastAPI dependency providing the configured Spotify client."""
    return build_spotify_client(get_settings())
