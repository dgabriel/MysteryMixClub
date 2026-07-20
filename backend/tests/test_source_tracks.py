"""Unit tests for app.services.source_tracks (MYS-201).

Pure helpers for source-only track identity: the ``source_key`` regex, the exact
URL each key reconstructs to, the response-model ``(source, source_url)`` pair,
and the YouTube video-id extractor. A source_key is an *exact* reference and is
never fuzzy-matched, so these guard that the key ⇄ URL mapping is byte-exact and
that the pattern accepts only well-formed keys.
"""

import re

import pytest

from app.services.source_tracks import (
    SOURCE_KEY_PATTERN,
    source_fields,
    source_url_for,
    youtube_video_id_from_key,
)

_PATTERN = re.compile(SOURCE_KEY_PATTERN)


# --------------------------------------------------------------------------- #
# SOURCE_KEY_PATTERN — accepts only well-formed keys
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "key",
    [
        "youtube:PRpiBpDy7MQ",
        "youtube:dQw4w9WgXcQ",
        "youtube:_-aBcDeFgH1",  # leading underscore/hyphen are valid base64url chars
        "bandcamp:coolband/song-title",
        "bandcamp:a/b",  # single-char slugs
        "bandcamp:coolband2/track-2-remix",
    ],
)
def test_pattern_accepts_valid_keys(key):
    assert _PATTERN.match(key)


@pytest.mark.parametrize(
    "key",
    [
        "",
        "not a key",
        "spotify:3PfIrDoz19",  # unsupported source prefix
        "youtube:short",  # < 11 chars
        "youtube:toolongvideoid",  # > 11 chars
        "youtube:has spaces1",  # space is not a base64url char
        "youtube:PRpiBpDy7M",  # 10 chars
        "bandcamp:CoolBand/song",  # uppercase artist slug rejected
        "bandcamp:coolband/Song",  # uppercase track slug rejected
        "bandcamp:-artist/track",  # leading hyphen rejected
        "bandcamp:artist/-track",  # leading hyphen on track rejected
        "bandcamp:artist",  # missing /track segment
        "bandcamp:artist/",  # empty track slug
        "bandcamp:../etc/passwd",  # path traversal — dots not allowed in a slug
        "bandcamp:artist/track/extra",  # extra path segment
        "YOUTUBE:PRpiBpDy7MQ",  # uppercase prefix rejected
        " youtube:PRpiBpDy7MQ",  # leading whitespace not part of the key
    ],
)
def test_pattern_rejects_malformed_keys(key):
    assert not _PATTERN.match(key)


# --------------------------------------------------------------------------- #
# source_url_for — exact URL reconstruction
# --------------------------------------------------------------------------- #


def test_source_url_for_youtube_is_exact_watch_link():
    source, url = source_url_for("youtube:PRpiBpDy7MQ")
    assert source == "youtube"
    assert url == "https://www.youtube.com/watch?v=PRpiBpDy7MQ"


def test_source_url_for_bandcamp_is_exact_track_page():
    source, url = source_url_for("bandcamp:coolband/song-title")
    assert source == "bandcamp"
    assert url == "https://coolband.bandcamp.com/track/song-title"


@pytest.mark.parametrize("key", ["", "spotify:abc", "youtube:short", "garbage"])
def test_source_url_for_raises_on_malformed_key(key):
    with pytest.raises(ValueError):
        source_url_for(key)


# --------------------------------------------------------------------------- #
# source_fields — the (source, source_url) pair for a response model
# --------------------------------------------------------------------------- #


def test_source_fields_none_for_catalog_track():
    # A normal ISRC-backed submission has no source_key.
    assert source_fields(None) == (None, None)


def test_source_fields_youtube():
    assert source_fields("youtube:PRpiBpDy7MQ") == (
        "youtube",
        "https://www.youtube.com/watch?v=PRpiBpDy7MQ",
    )


def test_source_fields_bandcamp():
    assert source_fields("bandcamp:coolband/song-title") == (
        "bandcamp",
        "https://coolband.bandcamp.com/track/song-title",
    )


# --------------------------------------------------------------------------- #
# youtube_video_id_from_key — the bare id, or None for a non-youtube key
# --------------------------------------------------------------------------- #


def test_youtube_video_id_from_key_returns_id():
    assert youtube_video_id_from_key("youtube:PRpiBpDy7MQ") == "PRpiBpDy7MQ"


def test_youtube_video_id_from_key_none_for_bandcamp():
    assert youtube_video_id_from_key("bandcamp:coolband/song-title") is None
