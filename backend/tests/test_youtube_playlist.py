"""Unit tests for the YouTube playlist helpers (MYS-78).

Covers ``youtube_video_id_from_url`` URL parsing and ``build_watch_videos_url``
list assembly. Both are pure — no network, no DB.
"""

import pytest

from app.services.odesli import youtube_video_id_from_url
from app.services.youtube_playlist import build_watch_videos_url, normalize_video_ids


# --------------------------------------------------------------------------- #
# youtube_video_id_from_url
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtube.com/watch?v=abc123", "abc123"),
        ("https://music.youtube.com/watch?v=XYZ_987", "XYZ_987"),
        ("https://m.youtube.com/watch?v=abc123", "abc123"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/abc123?t=42", "abc123"),
        # Extra query params alongside v= still parse.
        ("https://www.youtube.com/watch?list=PL1&v=abc123&t=10", "abc123"),
    ],
)
def test_parses_accepted_watch_urls(url, expected):
    assert youtube_video_id_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        # Search / deep links carry no video id.
        "https://music.youtube.com/search?q=bad%20guy",
        "https://www.youtube.com/results?search_query=bad+guy",
        # watch URL without a v param.
        "https://www.youtube.com/watch",
        # Non-YouTube hosts.
        "https://open.spotify.com/track/2",
        "https://www.deezer.com/track/4",
        # Not a URL at all.
        "not a url",
        "youtube.com/watch?v=abc123",
        "",
    ],
)
def test_returns_none_for_non_watch_inputs(url):
    assert youtube_video_id_from_url(url) is None


def test_returns_none_for_none():
    assert youtube_video_id_from_url(None) is None


# --------------------------------------------------------------------------- #
# build_watch_videos_url
# --------------------------------------------------------------------------- #


def test_builds_url_preserving_order():
    url = build_watch_videos_url(["a", "b", "c"])
    assert url == "https://www.youtube.com/watch_videos?video_ids=a%2Cb%2Cc"


def test_dedupes_preserving_first_seen_order():
    url = build_watch_videos_url(["a", "b", "a", "c", "b"])
    assert url == "https://www.youtube.com/watch_videos?video_ids=a%2Cb%2Cc"


def test_caps_at_fifty():
    ids = [f"id{i}" for i in range(60)]
    url = build_watch_videos_url(ids)
    assert url is not None
    # Decode the comma-joined list back out and count.
    joined = url.split("video_ids=", 1)[1].replace("%2C", ",")
    assert len(joined.split(",")) == 50
    assert joined.split(",")[0] == "id0"
    assert joined.split(",")[-1] == "id49"


def test_empty_returns_none():
    assert build_watch_videos_url([]) is None


def test_all_empty_strings_return_none():
    assert build_watch_videos_url(["", ""]) is None


# --------------------------------------------------------------------------- #
# normalize_video_ids — the count and the URL must agree, so the route derives
# both from this one normalized list.
# --------------------------------------------------------------------------- #


def test_normalize_dedupes_and_preserves_order():
    assert normalize_video_ids(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_normalize_drops_empty_strings():
    assert normalize_video_ids(["a", "", "b"]) == ["a", "b"]


def test_normalize_caps_at_fifty():
    ids = [f"id{i}" for i in range(60)]
    normalized = normalize_video_ids(ids)
    assert len(normalized) == 50
    assert normalized[0] == "id0"
    assert normalized[-1] == "id49"


def test_normalize_matches_url_contents():
    ids = ["a", "b", "a", "c"]
    normalized = normalize_video_ids(ids)
    url = build_watch_videos_url(ids)
    assert url is not None
    joined = url.split("video_ids=", 1)[1].replace("%2C", ",")
    assert joined.split(",") == normalized
