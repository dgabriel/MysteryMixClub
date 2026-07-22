"""Unit tests for app.services.youtube_resolver (MYS-78).

HTTP is mocked via httpx.MockTransport injected through the client factory, so no
network is touched and no real API key is needed. Covers the happy path plus
every best-effort fallback: empty key, non-200 (quota/auth), no items, timeout,
and transport error — all of which must yield None rather than raise.
"""

import httpx

from app.services.youtube_resolver import YouTubeResolver

# A representative YouTube Data API search.list response (trimmed to the fields
# the resolver reads).
SEARCH_PAYLOAD = {
    "kind": "youtube#searchListResponse",
    "items": [
        {
            "id": {"kind": "youtube#video", "videoId": "PRpiBpDy7MQ"},
            "snippet": {"title": "American Pie"},
        }
    ],
}


def _resolver(handler, *, api_key: str = "test-key") -> YouTubeResolver:
    """YouTubeResolver whose every request is served by ``handler``."""

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return YouTubeResolver(api_key=api_key, client_factory=factory)


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


async def test_returns_top_video_id():
    vid = await _resolver(lambda r: httpx.Response(200, json=SEARCH_PAYLOAD)).video_id_for(
        "American Pie", "Don McLean"
    )
    assert vid == "PRpiBpDy7MQ"


async def test_sends_expected_query_params():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    await _resolver(handler, api_key="secret").video_id_for("American Pie", "Don McLean")
    assert seen["part"] == "snippet"
    assert seen["q"] == "American Pie Don McLean"
    assert seen["type"] == "video"
    assert seen["maxResults"] == "5"
    assert seen["key"] == "secret"


async def test_query_without_artist_uses_title_only():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=SEARCH_PAYLOAD)

    await _resolver(handler).video_id_for("American Pie", None)
    assert seen["q"] == "American Pie"


# --------------------------------------------------------------------------- #
# Best-effort fallbacks — every failure yields None, never raises.
# --------------------------------------------------------------------------- #


async def test_empty_api_key_returns_none_without_request():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call should be made without an API key")

    assert await _resolver(handler, api_key="").video_id_for("American Pie", None) is None


async def test_empty_title_returns_none_without_request():
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP call should be made for an empty title")

    assert await _resolver(handler).video_id_for("   ", None) is None


async def test_non_200_quota_returns_none():
    assert await _resolver(lambda r: httpx.Response(403)).video_id_for("x", None) is None


async def test_no_items_returns_none():
    assert (
        await _resolver(lambda r: httpx.Response(200, json={"items": []})).video_id_for("x", None)
        is None
    )


async def test_missing_video_id_field_returns_none():
    payload = {"items": [{"id": {"kind": "youtube#channel"}}]}
    assert (
        await _resolver(lambda r: httpx.Response(200, json=payload)).video_id_for("x", None) is None
    )


# --------------------------------------------------------------------------- #
# Relevance ranking (MYS-175) — the API's own top hit is not trusted blindly.
# --------------------------------------------------------------------------- #


async def test_picks_best_title_match_not_first_result():
    # Regression case: searching "Storm II" by GENER8ION should not surface an
    # unrelated top hit just because the API returned it first.
    payload = {
        "items": [
            {"id": {"videoId": "unrelated1"}, "snippet": {"title": "Totally Different Song"}},
            {"id": {"videoId": "correct1"}, "snippet": {"title": "GENER8ION - Storm II (Audio)"}},
        ]
    }
    vid = await _resolver(lambda r: httpx.Response(200, json=payload)).video_id_for(
        "Storm II", "GENER8ION"
    )
    assert vid == "correct1"


async def test_penalizes_karaoke_version_over_original():
    payload = {
        "items": [
            {"id": {"videoId": "karaoke1"}, "snippet": {"title": "American Pie (Karaoke Version)"}},
            {"id": {"videoId": "original1"}, "snippet": {"title": "Don McLean - American Pie"}},
        ]
    }
    vid = await _resolver(lambda r: httpx.Response(200, json=payload)).video_id_for(
        "American Pie", "Don McLean"
    )
    assert vid == "original1"


async def test_prefers_official_channel_over_a_slightly_better_title_match():
    # Real repro (MYS-175): a reupload's title matches the query more closely,
    # but the artist's own channel is preferred when it's a plausible match too.
    payload = {
        "items": [
            {
                "id": {"videoId": "reupload"},
                "snippet": {
                    "title": "Artist - Song Title (Audio)",
                    "channelTitle": "Random Uploader",
                },
            },
            {
                "id": {"videoId": "official"},
                "snippet": {"title": "Artist - Song", "channelTitle": "Artist"},
            },
        ]
    }
    vid = await _resolver(lambda r: httpx.Response(200, json=payload)).video_id_for(
        "Song Title", "Artist"
    )
    assert vid == "official"


async def test_timeout_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    assert await _resolver(handler).video_id_for("x", None) is None


async def test_transport_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    assert await _resolver(handler).video_id_for("x", None) is None


async def test_non_json_body_returns_none():
    assert (
        await _resolver(lambda r: httpx.Response(200, text="not json")).video_id_for("x", None)
        is None
    )
