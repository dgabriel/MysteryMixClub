"""Unit tests for the YouTube playlist helpers (MYS-78).

Covers ``build_watch_videos_url`` / ``normalize_video_ids`` list assembly. Both
are pure — no network, no DB.
"""

from app.services.youtube_playlist import build_watch_videos_url, normalize_video_ids


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
