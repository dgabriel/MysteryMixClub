"""Unit tests for the OAuth-state helpers in app.auth.jwt (MYS-83)."""

import uuid

import pytest
from jose import JWTError

from app.auth.jwt import create_oauth_state, decode_oauth_state


def test_roundtrip_returns_user_id_and_no_return_path_by_default():
    uid = uuid.uuid4()
    decoded = decode_oauth_state(create_oauth_state(uid, "spotify"), "spotify")
    assert decoded.user_id == uid
    assert decoded.return_to is None


def test_roundtrip_carries_return_path():
    uid = uuid.uuid4()
    decoded = decode_oauth_state(create_oauth_state(uid, "spotify", "/mixes/abc"), "spotify")
    assert decoded.user_id == uid
    assert decoded.return_to == "/mixes/abc"


def test_purpose_mismatch_rejected():
    # A state minted for one provider can't be replayed against another.
    state = create_oauth_state(uuid.uuid4(), "spotify")
    with pytest.raises(JWTError):
        decode_oauth_state(state, "deezer")


def test_tampered_state_rejected():
    state = create_oauth_state(uuid.uuid4(), "spotify")
    with pytest.raises(JWTError):
        decode_oauth_state(state + "x", "spotify")
