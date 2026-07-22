"""Unit tests for app.services.deezer_search (MYS-44).

HTTP is mocked via httpx.MockTransport. Covers normalization (incl. inline ISRC
+ album art + resolve_url), the too_many_results heuristic, Deezer's HTTP-200
error body (quota -> rate limit), timeout/unavailable branches, and the
in-process TTL cache (a hit serves without re-hitting Deezer).
"""

import httpx
import pytest

from app.services.deezer_search import (
    DeezerError,
    DeezerRateLimitError,
    DeezerSearchClient,
    DeezerTimeoutError,
    DeezerUnavailableError,
    _TTLCache,
)


def _item(idx: int) -> dict:
    return {
        "id": 100 + idx,
        "title": f"Song {idx}",
        "link": f"https://www.deezer.com/track/{100 + idx}",
        "isrc": f"ISRC{idx:08d}",
        "artist": {"name": "Artist A"},
        "album": {
            "title": "Album X",
            "cover": "https://img/cover.jpg",
            "cover_medium": "https://img/cover_medium.jpg",
        },
    }


def _body(n: int, total: int) -> dict:
    return {"data": [_item(i) for i in range(n)], "total": total}


class _Recorder:
    """Serves a canned response and records every request URL."""

    def __init__(self, response: httpx.Response):
        self.calls: list[httpx.Request] = []
        self._response = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self._response


def _client(handler) -> DeezerSearchClient:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return DeezerSearchClient(client_factory=factory)


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #


async def test_search_normalizes_tracks():
    result = await _client(_Recorder(httpx.Response(200, json=_body(2, 2)))).search("debaser")

    assert len(result.results) == 2
    t = result.results[0]
    assert t.id == "100"
    assert t.title == "Song 0"
    assert t.artist == "Artist A"
    assert t.album == "Album X"
    assert t.thumbnail_url == "https://img/cover_medium.jpg"
    assert t.isrc == "ISRC00000000"
    assert t.resolve_url == "https://www.deezer.com/track/100"


async def test_search_skips_items_missing_id_or_title():
    body = {"data": [{"title": "no id"}, _item(1)], "total": 2}
    result = await _client(_Recorder(httpx.Response(200, json=body))).search("x")
    assert [t.id for t in result.results] == ["101"]


async def test_search_reranks_results_by_relevance():
    # Deezer's own order (a live/cover version first) shouldn't win over the
    # closer title+artist match to the query (MYS-175).
    body = {
        "data": [
            {
                "id": 1,
                "title": "Storm II (Live)",
                "artist": {"name": "Cover Band"},
                "link": "https://www.deezer.com/track/1",
            },
            {
                "id": 2,
                "title": "Storm II",
                "artist": {"name": "GENER8ION"},
                "link": "https://www.deezer.com/track/2",
            },
        ],
        "total": 2,
    }
    result = await _client(_Recorder(httpx.Response(200, json=body))).search(
        "Storm II", "GENER8ION"
    )
    assert result.results[0].id == "2"


# --------------------------------------------------------------------------- #
# too_many_results heuristic + query building
# --------------------------------------------------------------------------- #


async def test_too_many_results_true_when_no_artist_and_total_over_limit():
    result = await _client(_Recorder(httpx.Response(200, json=_body(10, 76)))).search("love")
    assert result.too_many_results is True
    assert len(result.results) == 10


async def test_too_many_results_false_when_artist_supplied():
    result = await _client(_Recorder(httpx.Response(200, json=_body(10, 76)))).search(
        "love", "a-ha"
    )
    assert result.too_many_results is False


async def test_too_many_results_false_when_total_within_limit():
    result = await _client(_Recorder(httpx.Response(200, json=_body(3, 3)))).search("specific")
    assert result.too_many_results is False


async def test_artist_builds_advanced_query():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me", "a-ha")
    q = dict(rec.calls[0].url.params)["q"]
    assert 'track:"take on me"' in q
    assert 'artist:"a-ha"' in q


async def test_no_artist_uses_plain_query():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me")
    assert dict(rec.calls[0].url.params)["q"] == "take on me"


async def test_quotes_are_stripped_from_advanced_query():
    # A double-quote in title/artist would corrupt Deezer's artist:"" track:""
    # filter grammar (no escaping); they must be removed before interpolation.
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search('That\'s Heavenly To Me "Live"', 'Sam "The Man" Cooke')
    q = dict(rec.calls[0].url.params)["q"]
    assert '"Live"' not in q
    # Exactly the two filter-delimiter quote pairs remain, none stray.
    assert q.count('"') == 4


async def test_quotes_are_stripped_from_plain_query():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search('say "hello"')
    assert '"' not in dict(rec.calls[0].url.params)["q"]


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #


async def test_identical_search_is_served_from_cache():
    rec = _Recorder(httpx.Response(200, json=_body(2, 2)))
    client = _client(rec)
    await client.search("Debaser", "Pixies")
    await client.search("debaser", "pixies")  # case-insensitive same key
    assert len(rec.calls) == 1


def test_ttlcache_expires_entries(monkeypatch):
    import app.services.deezer_search as mod

    now = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: now["t"])
    cache = _TTLCache(ttl=10.0, maxsize=8)
    from app.services.deezer_search import SongSearchResult

    cache.set("k", SongSearchResult(results=[]))
    assert cache.get("k") is not None
    now["t"] += 11.0
    assert cache.get("k") is None


# --------------------------------------------------------------------------- #
# Error states
# --------------------------------------------------------------------------- #


async def test_empty_title_raises_before_request():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    with pytest.raises(DeezerError):
        await _client(rec).search("   ")
    assert rec.calls == []


async def test_quota_error_body_raises_rate_limit():
    # Deezer returns quota errors as HTTP 200 with an error body, code 4.
    body = {"error": {"type": "Exception", "code": 4, "message": "Quota limit exceeded"}}
    with pytest.raises(DeezerRateLimitError):
        await _client(_Recorder(httpx.Response(200, json=body))).search("x")


async def test_other_error_body_raises_unavailable():
    body = {"error": {"type": "DataException", "code": 800, "message": "no data"}}
    with pytest.raises(DeezerUnavailableError):
        await _client(_Recorder(httpx.Response(200, json=body))).search("x")


async def test_non_200_raises_unavailable():
    with pytest.raises(DeezerUnavailableError):
        await _client(_Recorder(httpx.Response(503))).search("x")


async def test_timeout_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DeezerTimeoutError):
        await _client(handler).search("x")


async def test_transport_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(DeezerUnavailableError):
        await _client(handler).search("x")
