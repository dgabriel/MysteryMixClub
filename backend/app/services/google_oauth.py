"""Google Sign-In OAuth client (MysteryMixClub-ali8.2, ADR 0007).

Owns every interaction with Google's OAuth surfaces so the route layer sees only
a verified identity or a typed error. Structurally this mirrors
:mod:`app.services.spotify_client` — same authorization-code shape, same
``is_configured`` gate, same injectable ``client_factory`` so tests never touch
the network.

**Why userinfo rather than verifying the ID token's signature.** The access
token here is one we obtained ourselves, by POSTing our own client_id/secret
plus the authorization code straight to Google's token endpoint over TLS. It
never passes through the browser, so there is no attacker-supplied JWT to
validate — Google's own guidance is that signature verification is for tokens
received from a client, not ones fetched directly over a secure channel. Calling
``/userinfo`` with that token asks Google who it belongs to and gets an
authenticated answer, which is the same trust anchor the signature would give
us, using ``httpx`` (already a dependency) instead of adding ``google-auth``
(synchronous, so it would need its own thread offload, plus its own cert
fetching and caching).

``email_verified`` is still checked by the caller: an unverified Google address
proves nothing about who owns that mailbox.

Reference: https://developers.google.com/identity/protocols/oauth2/web-server
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx

from app.auth.tokens import generate_token
from app.config import Settings, get_settings

_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_DEFAULT_TIMEOUT = 10.0

# Identity only — no Google API access beyond knowing who signed in.
_SCOPES = ("openid", "email", "profile")


def _safe_body(response: httpx.Response, limit: int = 300) -> str:
    """A truncated response body for exception messages/logs. Never raises."""
    try:
        return response.text[:limit]
    except Exception:  # noqa: BLE001 — body is diagnostic only, never fatal
        return "<unreadable body>"


class GoogleAuthError(RuntimeError):
    """Google rejected the authorization code or the access token."""


class GoogleApiError(RuntimeError):
    """A Google call failed in a way the caller should surface."""


@dataclass(frozen=True)
class GoogleIdentity:
    """The signed-in Google account, as Google reports it.

    ``subject`` is Google's stable per-account id (the ``sub`` claim) — the value
    to persist, since a user can change their Gmail address but never their
    ``sub``.
    """

    subject: str
    email: str
    email_verified: bool


class GoogleOAuthClient:
    """Async wrapper over Google's OAuth + userinfo endpoints.

    ``client_factory`` lets tests inject an ``httpx.AsyncClient`` backed by a
    mock transport; in production it defaults to a real client with a timeout.
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
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))

    @property
    def is_configured(self) -> bool:
        """True only when client id, secret, and redirect URI are all present."""
        return bool(self._client_id and self._client_secret and self._redirect_uri)

    def authorize_url(self, state: str, code_challenge: str) -> str:
        """Build the Google consent URL to redirect the user to.

        ``state`` is the signed round-trip value the callback verifies.
        ``code_challenge`` is the PKCE challenge for this flow
        (MysteryMixClub-ali8.7) — see :func:`generate_pkce_pair`.
        """
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": " ".join(_SCOPES),
            "state": state,
            # Sign-in only ever needs an identity, so no refresh token is
            # requested and no offline access is kept.
            "access_type": "online",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, code_verifier: str) -> str:
        """Exchange an authorization ``code`` for an access token. Raises on
        failure.

        ``code_verifier`` is PKCE's code-to-flow binding (MysteryMixClub-
        ali8.7): Google checks it hashes to the ``code_challenge`` sent to
        ``authorize_url`` for this same ``state``, so a code obtained via a
        separate leak (referrer, open redirect, log exposure) can't be
        replayed from a different flow that never had the matching verifier.
        """
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "code_verifier": code_verifier,
        }
        try:
            async with self._client_factory() as client:
                response = await client.post(_TOKEN_URL, data=data)
        except httpx.HTTPError as exc:
            raise GoogleApiError(f"google token request failed: {exc}") from exc

        if response.status_code in (400, 401):
            # invalid_grant: a reused, expired, or forged code.
            raise GoogleAuthError(f"google rejected the authorization code: {_safe_body(response)}")
        if response.status_code != 200:
            raise GoogleApiError(
                f"google token request returned {response.status_code}: {_safe_body(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleApiError("google token response was not JSON") from exc

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise GoogleApiError("google token response carried no access_token")
        return access_token

    async def fetch_identity(self, access_token: str) -> GoogleIdentity:
        """Ask Google who the access token belongs to. Raises on failure."""
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    _USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
                )
        except httpx.HTTPError as exc:
            raise GoogleApiError(f"google userinfo request failed: {exc}") from exc

        if response.status_code == 401:
            raise GoogleAuthError("google rejected the access token")
        if response.status_code != 200:
            raise GoogleApiError(
                f"google userinfo returned {response.status_code}: {_safe_body(response)}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleApiError("google userinfo response was not JSON") from exc

        subject = payload.get("sub")
        email = payload.get("email")
        if not isinstance(subject, str) or not subject:
            raise GoogleApiError("google userinfo carried no sub")
        if not isinstance(email, str) or not email:
            raise GoogleApiError("google userinfo carried no email")
        return GoogleIdentity(
            subject=subject,
            email=email,
            # Absent reads as unverified — never assume a claim Google didn't make.
            email_verified=payload.get("email_verified") is True,
        )


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for a fresh PKCE exchange
    (MysteryMixClub-ali8.7). S256, per Google's recommendation for web server
    apps: https://developers.google.com/identity/protocols/oauth2/web-server

    ``generate_token()`` already produces a 43-character URL-safe string --
    RFC 7636 requires 43-128 characters from ``[A-Za-z0-9-._~]``, and
    ``token_urlsafe``'s alphabet (``-``/``_`` plus alphanumerics) is a subset
    of that, so it's a valid ``code_verifier`` as-is with no new generator.
    """
    verifier = generate_token()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_google_oauth_client(settings: Settings) -> GoogleOAuthClient:
    return GoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )


@lru_cache
def get_google_oauth_client() -> GoogleOAuthClient:
    """FastAPI dependency providing the configured Google OAuth client."""
    return build_google_oauth_client(get_settings())
