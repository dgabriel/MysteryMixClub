"""Unit tests for app.services.spotify_token_crypto (MYS-83).

Relies on SECRET_KEY being configured (backend/.env in dev / CI env), the same
requirement as the JWT helpers.
"""

import pytest

from app.services.spotify_token_crypto import (
    SpotifyTokenCryptoError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)


def test_roundtrip():
    token = "AQA-spotify-refresh-token-value"
    encrypted = encrypt_refresh_token(token)
    assert encrypted != token  # actually encrypted, not stored in the clear
    assert decrypt_refresh_token(encrypted) == token


def test_ciphertext_is_nondeterministic():
    # Fernet embeds a random IV, so the same token encrypts differently each time
    # while still decrypting back to the same value.
    token = "same-token"
    a = encrypt_refresh_token(token)
    b = encrypt_refresh_token(token)
    assert a != b
    assert decrypt_refresh_token(a) == decrypt_refresh_token(b) == token


def test_tampered_ciphertext_raises():
    encrypted = encrypt_refresh_token("token")
    tampered = encrypted[:-2] + ("AA" if not encrypted.endswith("AA") else "BB")
    with pytest.raises(SpotifyTokenCryptoError):
        decrypt_refresh_token(tampered)


def test_garbage_input_raises():
    with pytest.raises(SpotifyTokenCryptoError):
        decrypt_refresh_token("not-a-fernet-token")
