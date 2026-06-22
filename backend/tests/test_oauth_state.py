"""Unit tests for the OAuth-state helpers in app.auth.jwt (MYS-83)."""

import uuid

import pytest
from jose import JWTError

from app.auth.jwt import create_oauth_state, decode_oauth_state


def test_roundtrip_returns_user_id():
    uid = uuid.uuid4()
    state = create_oauth_state(uid, "spotify")
    assert decode_oauth_state(state, "spotify") == uid


def test_purpose_mismatch_rejected():
    # A state minted for one provider can't be replayed against another.
    state = create_oauth_state(uuid.uuid4(), "spotify")
    with pytest.raises(JWTError):
        decode_oauth_state(state, "deezer")


def test_tampered_state_rejected():
    state = create_oauth_state(uuid.uuid4(), "spotify")
    with pytest.raises(JWTError):
        decode_oauth_state(state + "x", "spotify")
