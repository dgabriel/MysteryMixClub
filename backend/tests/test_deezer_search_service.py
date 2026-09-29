"""Unit tests for app.services.deezer_search (MYS-44).

HTTP is mocked via httpx.MockTransport. Covers normalization (incl. inline ISRC
+ album art + resolve_url), the too_many_results heuristic, Deezer's HTTP-200
error body (quota -> rate limit), timeout/unavailable branches, and the
in-process TTL cache (a hit serves without re-hitting Deezer).
"""

import logging

import httpx
import pytest

from app.services import deezer_search as deezer_module
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


async def test_artist_builds_track_filter_plus_plain_artist_term():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me", "a-ha")
    q = dict(rec.calls[0].url.params)["q"]
    assert q == 'track:"take on me" a-ha'


async def test_artist_search_fetches_a_wide_page_then_trims_to_ten_ranked():
    # Deezer treats the artist as a loose hint, so a common title buries the right
    # artist beyond row 10. Fetch wide, rank, trim: the right artist's track must
    # surface even when Deezer returned it last.
    noise = [dict(_item(i), artist={"name": "Someone Else"}, title="If") for i in range(24)]
    wanted = dict(_item(99), artist={"name": "Janet Jackson"}, title="If")
    rec = _Recorder(httpx.Response(200, json={"data": noise + [wanted], "total": 25}))
    result = await _client(rec).search("If", "Janet Jackson")
    assert dict(rec.calls[0].url.params)["limit"] == "50"
    assert len(result.results) == 10
    assert result.results[0].artist == "Janet Jackson"


async def test_no_artist_search_keeps_the_narrow_page():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me")
    assert dict(rec.calls[0].url.params)["limit"] == "10"


async def test_artist_never_uses_the_dead_artist_filter():
    # Deezer's artist:"..." filter returns HTTP 200 + empty data for every query
    # (2026-09-23 on, MysteryMixClub-0ui0). Guard against reintroducing it.
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("Until It Sleeps", "Metallica")
    assert "artist:" not in dict(rec.calls[0].url.params)["q"]


class _LogCollector(logging.Handler):
    """Collects this module's log records. Not ``caplog``: ``app/main.py`` sets
    ``propagate = False`` on the ``app`` logger, so records never reach the root
    logger caplog listens on (same reason test_push_notifications.py attaches
    its own handler)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())

    @property
    def text(self) -> str:
        return "\n".join(self.messages)


@pytest.fixture
def deezer_logs():
    handler = _LogCollector()
    previous_level = deezer_module.logger.level
    deezer_module.logger.setLevel(logging.DEBUG)
    deezer_module.logger.addHandler(handler)
    try:
        yield handler
    finally:
        deezer_module.logger.removeHandler(handler)
        deezer_module.logger.setLevel(previous_level)


async def test_zero_results_with_artist_logs_a_warning(deezer_logs):
    rec = _Recorder(httpx.Response(200, json={"data": [], "total": 0}))
    result = await _client(rec).search("Secret Song Title", "Secret Artist")
    assert result.results == []
    assert "zero results for an artist-qualified search" in deezer_logs.text
    # The query is user input; it must not reach the logs.
    assert "Secret" not in deezer_logs.text


async def test_zero_results_without_artist_does_not_warn(deezer_logs):
    rec = _Recorder(httpx.Response(200, json={"data": [], "total": 0}))
    await _client(rec).search("nothing matches this")
    assert deezer_logs.messages == []


async def test_results_with_artist_do_not_warn(deezer_logs):
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me", "a-ha")
    assert deezer_logs.messages == []


async def test_no_artist_uses_plain_query():
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search("take on me")
    assert dict(rec.calls[0].url.params)["q"] == "take on me"


async def test_quotes_are_stripped_from_advanced_query():
    # A double-quote in title/artist would corrupt Deezer's track:"" filter
    # grammar (no escaping); they must be removed before interpolation.
    rec = _Recorder(httpx.Response(200, json=_body(1, 1)))
    await _client(rec).search('That\'s Heavenly To Me "Live"', 'Sam "The Man" Cooke')
    q = dict(rec.calls[0].url.params)["q"]
    assert '"Live"' not in q
    # Exactly the one filter-delimiter quote pair remains, none stray.
    assert q.count('"') == 2


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
