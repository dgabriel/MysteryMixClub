"""Sign in with Apple identity-token verification (MysteryMixClub-4vii.9).

Structurally the odd one out among this app's OAuth-ish integrations. Google's
web flow (app.services.google_oauth) deliberately avoids verifying a JWT
signature at all -- it fetches the access token itself over a server-to-server
TLS call and asks Google's own /userinfo who it belongs to, so there's no
attacker-supplied token in play. Apple's *native* flow has no equivalent
second call: `ASAuthorizationController` hands the plugin a signed identity
token directly, and that token IS the credential the client is handing us, so
its signature has to be verified the same way a browser-presented JWT would
be anywhere else -- against Apple's own rotating public keys.

This is the one deliberate second call site for `jose` in this codebase
(app/auth/jwt.py's own module docstring confines *our* signing to itself) --
different concern: that module signs and verifies tokens *this app* mints
with its own HS256 secret, this module verifies a token *Apple* minted with
its own rotating RS256 keypair. Reusing jwt.py's `secret_key` would be
meaningless here; there's no shared secret with Apple to reuse.

No client secret or private key lives on this side: unlike Google (client
secret) or Apple Music (an ES256 signing key, app.services.apple_music_token),
verifying someone else's signature needs only their public key, which Apple
publishes at `_APPLE_KEYS_URL` for anyone to fetch.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache

import httpx
from jose import jwk, jwt
from jose.exceptions import JOSEError
from jose.utils import base64url_decode

_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"
_DEFAULT_TIMEOUT = 10.0
# Apple rotates keys infrequently; refetching once a day comfortably beats any
# rotation window while avoiding a network call on every sign-in.
_KEYS_CACHE_TTL = 24 * 60 * 60


class AppleSignInError(RuntimeError):
    """The identity token failed verification: bad signature, wrong audience
    or issuer, expired, or malformed."""


@dataclass(frozen=True)
class AppleIdentity:
    """The signed-in Apple account, as its identity token attests.

    ``subject`` is Apple's stable per-account id (the `sub` claim) -- the
    value to persist, mirroring GoogleIdentity.subject. ``is_private_email``
    flags Apple's "Hide My Email" relay address: real, deliverable, and fully
    verified by Apple, but never proof the person controls any *other*
    account's inbox, so callers must not use it the way a real address is
    used for cross-provider email matching (MysteryMixClub-4vii.9 identity-
    conflict hardening).
    """

    subject: str
    email: str
    email_verified: bool
    is_private_email: bool


class AppleKeyFetchError(RuntimeError):
    """Apple's JWKS endpoint could not be reached or returned garbage."""


class AppleJWKSClient:
    """Fetches and caches Apple's public signing keys.

    A thin, injectable wrapper (same shape as GoogleOAuthClient's
    ``client_factory``) so tests supply canned keys instead of hitting the
    network, and production gets a real timeout.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        cache_ttl: float = _KEYS_CACHE_TTL,
    ) -> None:
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
        self._cache_ttl = cache_ttl
        self._cached_keys: dict[str, dict] | None = None
        self._cached_at: float = 0.0

    async def get_key(self, kid: str) -> dict:
        """Return the JWK matching ``kid``, refetching the key set if it's
        missing (covers Apple rotating in a new key between our cache
        refreshes) or the cache has simply gone stale."""
        now = time.monotonic()
        if self._cached_keys is None or now - self._cached_at > self._cache_ttl:
            await self._refresh()
        if self._cached_keys is not None and kid in self._cached_keys:
            return self._cached_keys[kid]
        # Not found even after a fresh fetch — force one more refresh in case
        # Apple rotated keys since our last cache write, then give up.
        await self._refresh()
        if self._cached_keys is None or kid not in self._cached_keys:
            raise AppleKeyFetchError(f"no Apple signing key found for kid={kid!r}")
        return self._cached_keys[kid]

    async def _refresh(self) -> None:
        try:
            async with self._client_factory() as client:
                response = await client.get(_APPLE_KEYS_URL)
        except httpx.HTTPError as exc:
            raise AppleKeyFetchError(f"could not reach Apple's JWKS endpoint: {exc}") from exc
        if response.status_code != 200:
            raise AppleKeyFetchError(f"Apple's JWKS endpoint returned {response.status_code}")
        try:
            payload = response.json()
            keys = {key["kid"]: key for key in payload["keys"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise AppleKeyFetchError("Apple's JWKS response was malformed") from exc
        self._cached_keys = keys
        self._cached_at = time.monotonic()


async def verify_apple_identity_token(
    identity_token: str, *, bundle_id: str, keys_client: AppleJWKSClient
) -> AppleIdentity:
    """Verify ``identity_token`` and return the identity it attests to.

    Raises :class:`AppleSignInError` on any failure — bad signature, wrong
    audience/issuer, expired, or malformed. The caller (the /auth/apple/*
    route) treats any of these identically: reject the sign-in, no session
    issued.
    """
    # Every message below is a fixed, static string -- deliberately never
    # interpolating a claim value or a wrapped library exception's own text.
    # This is what actually gets logged (auth.py's apple_native_sign_in logs
    # str(exc) on failure for diagnosability), and an identity token's claims
    # (email, subject) are personal data that has no business in a log line;
    # the failure *category* below is all a log needs.
    try:
        header = jwt.get_unverified_header(identity_token)
    except JOSEError as exc:
        raise AppleSignInError("malformed identity token") from exc
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise AppleSignInError("identity token header carried no kid")

    try:
        key = await keys_client.get_key(kid)
    except AppleKeyFetchError as exc:
        # Safe to pass through as-is: describes OUR OWN request to Apple's
        # JWKS endpoint failing (network/HTTP status/malformed response),
        # never anything derived from the caller's identity token.
        raise AppleSignInError(str(exc)) from exc

    try:
        public_key = jwk.construct(key, algorithm="RS256")
        message, encoded_sig = identity_token.rsplit(".", 1)
        signature = base64url_decode(encoded_sig.encode("ascii"))
        if not public_key.verify(message.encode("ascii"), signature):
            raise AppleSignInError("identity token signature verification failed")
        claims = jwt.get_unverified_claims(identity_token)
    except JOSEError as exc:
        raise AppleSignInError("could not verify identity token") from exc

    if claims.get("iss") != _APPLE_ISSUER:
        raise AppleSignInError("unexpected issuer")
    if claims.get("aud") != bundle_id:
        raise AppleSignInError("unexpected audience")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        raise AppleSignInError("identity token has expired")

    subject = claims.get("sub")
    email = claims.get("email")
    if not isinstance(subject, str) or not subject:
        raise AppleSignInError("identity token carried no sub")
    if not isinstance(email, str) or not email:
        raise AppleSignInError("identity token carried no email")

    return AppleIdentity(
        subject=subject,
        email=email,
        # Apple sends this as the *string* "true"/"false", not a JSON bool.
        email_verified=str(claims.get("email_verified", "")).lower() == "true",
        is_private_email=str(claims.get("is_private_email", "")).lower() == "true",
    )


@lru_cache
def get_apple_jwks_client() -> AppleJWKSClient:
    """FastAPI dependency providing the shared, process-lifetime JWKS cache."""
    return AppleJWKSClient()
