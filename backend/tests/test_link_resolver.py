"""Unit tests for app.services.link_resolver (MYS-81).

Every upstream (Deezer track + search, iTunes lookup, Spotify/YouTube oEmbed) is
mocked via httpx.MockTransport injected through the resolver's client_factory —
no network is touched. A single routing handler dispatches by host/path so the
Apple/Spotify/YouTube funnel-through-Deezer-search paths can be exercised
end-to-end. Covers each platform, URL cleaning, invalid-url / not-found, and the
rate-limit / timeout / unavailable error mapping.
"""

import httpx
import pytest

from app.services.link_resolver import (
    InvalidSongURLError,
    LinkResolver,
    ResolverRateLimitError,
    ResolverTimeoutError,
    ResolverUnavailableError,
    SongNotFoundError,
    _bandcamp_track_id,
)

# Canonical Deezer search hit used by the Apple/Spotify/YouTube funnel.
_DEEZER_SEARCH_HIT = {
    "data": [
        {
            "id": 3156285,
            "title": "American Pie",
            "isrc": "USEM38600088",
            "artist": {"name": "Don McLean"},
            "album": {
                "title": "American Pie",
                "cover_medium": "https://img/deezer-med.jpg",
            },
            "link": "https://www.deezer.com/track/3156285",
        }
    ],
    "total": 1,
}

# Direct Deezer track lookup payload.
_DEEZER_TRACK = {
    "id": 3156285,
    "title": "American Pie",
    "isrc": "USEM38600088",
    "artist": {"name": "Don McLean"},
    "album": {
        "title": "American Pie",
        "cover_big": "https://img/deezer-big.jpg",
    },
}


def _router(*, search=None, track=None, itunes=None, spotify=None, youtube=None, bandcamp=None):
    """Build a MockTransport handler routing by host/path, with per-host overrides
    (a callable taking the request and returning an httpx.Response)."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if host == "api.deezer.com" and path.startswith("/search"):
            return (search or (lambda r: httpx.Response(200, json=_DEEZER_SEARCH_HIT)))(request)
        if host == "api.deezer.com" and path.startswith("/track/"):
            return (track or (lambda r: httpx.Response(200, json=_DEEZER_TRACK)))(request)
        if host == "itunes.apple.com" and path.startswith("/lookup"):
            return (itunes or (lambda r: httpx.Response(200, json={"results": []})))(request)
        if host == "open.spotify.com" and path.startswith("/oembed"):
            return (spotify or (lambda r: httpx.Response(200, json={})))(request)
        if host == "www.youtube.com" and path.startswith("/oembed"):
            return (youtube or (lambda r: httpx.Response(200, json={})))(request)
        if host == "bandcamp.com" or host.endswith(".bandcamp.com"):
            return (bandcamp or (lambda r: httpx.Response(404)))(request)
        raise AssertionError(f"unexpected request to {host}{path}")

    return handler


def _resolver(handler) -> LinkResolver:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return LinkResolver(client_factory=factory)


class _FakeSpotify:
    """Stands in for SpotifyClient.track_identity_by_id (exact Spotify-link path)."""

    def __init__(self, track):
        self._track = track
        self.looked_up: str | None = None

    async def track_identity_by_id(self, track_id):
        self.looked_up = track_id
        return self._track


def _resolver_with_spotify(handler, spotify) -> LinkResolver:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)

    return LinkResolver(client_factory=factory, spotify=spotify)


# --------------------------------------------------------------------------- #
# Deezer — direct track lookup
# --------------------------------------------------------------------------- #


async def test_deezer_direct_track():
    song = await _resolver(_router()).resolve("https://www.deezer.com/track/3156285")
    assert song.title == "American Pie"
    assert song.artist == "Don McLean"
    assert song.isrc == "USEM38600088"
    assert song.album == "American Pie"
    assert song.thumbnail_url == "https://img/deezer-big.jpg"


async def test_deezer_localized_path_track():
    # Localized form /en/track/{id} must still parse the id.
    song = await _resolver(_router()).resolve("https://www.deezer.com/en/track/3156285")
    assert song.isrc == "USEM38600088"


async def test_deezer_non_track_url_is_invalid():
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve("https://www.deezer.com/album/123")


async def test_deezer_track_error_body_is_not_found():
    handler = _router(track=lambda r: httpx.Response(200, json={"error": {"code": 800}}))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://www.deezer.com/track/999")


# --------------------------------------------------------------------------- #
# Apple Music — iTunes lookup -> Deezer search
# --------------------------------------------------------------------------- #


async def test_apple_funnels_through_deezer_search():
    seen: dict[str, str] = {}

    def itunes(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={"results": [{"trackName": "American Pie", "artistName": "Don McLean"}]},
        )

    handler = _router(itunes=itunes)
    url = "https://music.apple.com/us/album/american-pie/1440834532?i=1440834619"
    song = await _resolver(handler).resolve(url)
    assert seen["id"] == "1440834619"  # the ?i= track id is looked up
    assert song.title == "American Pie"
    assert song.artist == "Don McLean"
    assert song.isrc == "USEM38600088"  # recovered from Deezer


async def test_apple_without_track_id_is_invalid():
    url = "https://music.apple.com/us/album/american-pie/1440834532"
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve(url)


async def test_apple_lookup_empty_is_not_found():
    handler = _router(itunes=lambda r: httpx.Response(200, json={"results": []}))
    url = "https://music.apple.com/us/album/x/1?i=2"
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve(url)


async def test_apple_version_suffix_is_cleaned_before_search():
    # iTunes returns "American Pie (Full Length Version)"; the suffix must be
    # stripped or the strict Deezer query misses the canonical track.
    seen: dict[str, str] = {}

    def itunes(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {"trackName": "American Pie (Full Length Version)", "artistName": "Don McLean"}
                ]
            },
        )

    handler = _router(search=_search_spy(seen), itunes=itunes)
    url = "https://music.apple.com/us/album/x/1?i=2"
    song = await _resolver(handler).resolve(url)
    assert 'track:"American Pie"' in seen["q"]
    assert 'artist:"Don McLean"' in seen["q"]
    assert song.isrc == "USEM38600088"


# --------------------------------------------------------------------------- #
# Spotify — oEmbed (title only) -> Deezer search
# --------------------------------------------------------------------------- #


async def test_spotify_funnels_through_deezer_search():
    handler = _router(spotify=lambda r: httpx.Response(200, json={"title": "American Pie"}))
    url = "https://open.spotify.com/track/3PfIrDoz19wz7qK7tYeu62"
    song = await _resolver(handler).resolve(url)
    assert song.title == "American Pie"
    assert song.isrc == "USEM38600088"


async def test_spotify_uses_exact_api_identity_when_configured():
    # With Spotify configured we resolve the track id exactly (artist + ISRC) and
    # never touch the lossy oEmbed-title -> Deezer search that mis-matched
    # "Serpents" -> "Serpentskirt" (MYS-100).
    from app.services.spotify_client import SpotifyTrack

    fake = _FakeSpotify(
        SpotifyTrack(
            title="Serpents",
            artist="Sharon Van Etten",
            album="Epic",
            thumbnail_url="https://img/cover.jpg",
            isrc="US38Y1220103",
        )
    )

    def boom(_r):  # pragma: no cover - must not be hit on the exact path
        raise AssertionError("oEmbed/Deezer must not be called when the API resolves it")

    handler = _router(spotify=boom, search=boom)
    song = await _resolver_with_spotify(handler, fake).resolve(
        "https://open.spotify.com/track/2v05RhwIQx3zbN8O72Ff69"
    )
    assert (song.title, song.artist, song.isrc) == ("Serpents", "Sharon Van Etten", "US38Y1220103")
    assert fake.looked_up == "2v05RhwIQx3zbN8O72Ff69"


async def test_spotify_without_isrc_falls_back_to_deezer_with_artist():
    # If the Spotify record lacks an ISRC (rare), use its exact title+artist for an
    # accurate Deezer match — not a title-only search.
    from app.services.spotify_client import SpotifyTrack

    fake = _FakeSpotify(
        SpotifyTrack(
            title="American Pie", artist="Don McLean", album=None, thumbnail_url=None, isrc=None
        )
    )
    seen: dict = {}

    def search(request):
        seen["q"] = request.url.params.get("q", "")
        return httpx.Response(200, json=_DEEZER_SEARCH_HIT)

    handler = _router(search=search)
    song = await _resolver_with_spotify(handler, fake).resolve(
        "https://open.spotify.com/track/abc123"
    )
    assert song.title == "American Pie"
    assert song.isrc == "USEM38600088"
    assert "Don McLean" in seen["q"]  # artist included, not a title-only search


async def test_spotify_non_track_url_is_invalid():
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve("https://open.spotify.com/album/abc")


# --------------------------------------------------------------------------- #
# YouTube — oEmbed (noisy title) cleaned -> Deezer search
# --------------------------------------------------------------------------- #


def _search_spy(seen: dict[str, str]):
    def search(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        return httpx.Response(200, json=_DEEZER_SEARCH_HIT)

    return search


@pytest.mark.parametrize(
    "raw_title",
    [
        "American Pie [HD]",
        "American Pie (Audio) (HD)",
        "American Pie | Official Music Video",
        "American Pie (Remastered 2022)",
        "American Pie (Official Video)",
    ],
)
async def test_youtube_bare_title_is_cleaned_and_searched(raw_title):
    # A bare song title with a non-Topic channel: the channel ("...VEVO") is an
    # unreliable artist hint and is ignored — search the cleaned title alone.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"title": raw_title, "author_name": "DonMcLeanVEVO"})

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")
    assert seen["q"] == "American Pie"  # cleaned, no bogus artist filter
    assert song.isrc == "USEM38600088"


async def test_youtube_artist_dash_title_is_split():
    # VEVO/official "Artist - Title (noise)" -> split into a strict artist/track
    # query; the channel name is ignored.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "title": "Don McLean - American Pie (Lyric Video)",
                "author_name": "DonMcLeanVEVO",
            },
        )

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")
    assert 'artist:"Don McLean"' in seen["q"]
    assert 'track:"American Pie"' in seen["q"]
    assert song.isrc == "USEM38600088"


async def test_youtube_topic_channel_supplies_artist():
    # YouTube Music auto-channel: bare title + "Artist - Topic" author is reliable.
    seen: dict[str, str] = {}

    def youtube(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"title": "American Pie", "author_name": "Don McLean - Topic"}
        )

    handler = _router(search=_search_spy(seen), youtube=youtube)
    song = await _resolver(handler).resolve("https://music.youtube.com/watch?v=abc")
    assert 'artist:"Don McLean"' in seen["q"]
    assert 'track:"American Pie"' in seen["q"]
    assert song.isrc == "USEM38600088"


async def test_youtu_be_short_url_resolves():
    handler = _router(youtube=lambda r: httpx.Response(200, json={"title": "American Pie"}))
    song = await _resolver(handler).resolve("https://youtu.be/PRpiBpDy7MQ")
    assert song.isrc == "USEM38600088"


# --------------------------------------------------------------------------- #
# Bandcamp (MYS-200) — track page og:title ("Title, by Artist") -> Deezer search
# --------------------------------------------------------------------------- #


def _bandcamp_page(meta: str) -> str:
    """A minimal Bandcamp-style track page embedding the given <meta> tag."""
    return (
        "<!DOCTYPE html><html><head>"
        '<meta property="og:site_name" content="Cool Band">'
        f"{meta}"
        '<meta property="og:type" content="song">'
        "<title>ignored | Cool Band</title>"
        "</head><body></body></html>"
    )


def _bandcamp_ok(meta: str):
    return lambda r: httpx.Response(200, text=_bandcamp_page(meta))


@pytest.mark.parametrize(
    "url",
    [
        "https://coolband.bandcamp.com/track/song-title",
        "https://bandcamp.com/track/song-title",
    ],
)
async def test_bandcamp_track_funnels_through_deezer_search(url):
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok('<meta property="og:title" content="Song Title, by Artist Name">'),
    )
    song = await _resolver(handler).resolve(url)
    assert 'track:"Song Title"' in seen["q"]
    assert 'artist:"Artist Name"' in seen["q"]
    # Canonical identity comes from the Deezer hit, ISRC included.
    assert song.title == "American Pie"
    assert song.artist == "Don McLean"
    assert song.isrc == "USEM38600088"


async def test_bandcamp_content_first_attribute_order_and_entities():
    # Attribute order flipped (content before property) plus HTML entities in the
    # title — both must still parse and unescape before the split.
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok(
            '<meta content="Don&#39;t Stop, by Rock &amp; Roll Band" property="og:title">'
        ),
    )
    song = await _resolver(handler).resolve("https://x.bandcamp.com/track/dont-stop")
    assert 'track:"Don\'t Stop"' in seen["q"]
    assert 'artist:"Rock & Roll Band"' in seen["q"]
    assert song.isrc == "USEM38600088"


async def test_bandcamp_title_containing_by_splits_on_last():
    # A title can itself contain ", by " — the split must take the LAST one.
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok(
            '<meta property="og:title" content="Standing, by the Sea, by Cool Band">'
        ),
    )
    await _resolver(handler).resolve("https://coolband.bandcamp.com/track/standing-by-the-sea")
    assert 'track:"Standing, by the Sea"' in seen["q"]
    assert 'artist:"Cool Band"' in seen["q"]


async def test_bandcamp_title_without_by_searches_title_only():
    # No ", by " separator: the whole og:title is the title, artist None — so the
    # Deezer query is the bare title with no artist:""/track:"" filter grammar.
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok('<meta property="og:title" content="Untitled Track">'),
    )
    song = await _resolver(handler).resolve("https://x.bandcamp.com/track/untitled")
    assert seen["q"] == "Untitled Track"
    assert song.isrc == "USEM38600088"


async def test_bandcamp_follows_redirects_to_track_page():
    # Bandcamp artist pages occasionally 301; the fetch must follow through.
    def bandcamp(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/track/old-slug":
            return httpx.Response(
                301, headers={"Location": "https://coolband.bandcamp.com/track/new-slug"}
            )
        return httpx.Response(
            200,
            text=_bandcamp_page('<meta property="og:title" content="Song Title, by Artist Name">'),
        )

    handler = _router(bandcamp=bandcamp)
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/old-slug")
    assert song.isrc == "USEM38600088"


# --- Redirect hardening (SSRF) + body cap + attribute spoofing ---------------


def _recording_handler(route):
    """Wrap a request->Response callable, recording every request it serves."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return route(request)

    return handler, calls


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example.com/",
        "http://169.254.169.254/latest/meta-data/",
        "https://bandcamp.com.evil.com/track/x",  # suffix-spoofed host
        "ftp://coolband.bandcamp.com/track/x",  # right host, non-http scheme
    ],
)
async def test_bandcamp_hostile_redirect_is_rejected_and_never_fetched(location):
    # A redirect off the Bandcamp host family (or off http/https) must be
    # refused as not-found — and the hostile target must never be requested.
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location})

    handler, calls = _recording_handler(route)
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://coolband.bandcamp.com/track/x")
    # Only the original Bandcamp fetch happened; the redirect target was not.
    assert [c.url.host for c in calls] == ["coolband.bandcamp.com"]


async def test_bandcamp_redirect_without_location_is_not_found():
    handler, calls = _recording_handler(lambda r: httpx.Response(301))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://coolband.bandcamp.com/track/x")
    assert len(calls) == 1


async def test_bandcamp_redirect_chain_within_hop_budget_resolves():
    # 3 hops (the max) then a 200 page: resolves, in exactly 4 Bandcamp fetches.
    chain = {
        "/track/a": "https://coolband.bandcamp.com/track/b",
        "/track/b": "https://bandcamp.com/track/c",
        "/track/c": "https://other.bandcamp.com/track/d",
    }

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.deezer.com":
            return httpx.Response(200, json=_DEEZER_SEARCH_HIT)
        target = chain.get(request.url.path)
        if target:
            return httpx.Response(302, headers={"Location": target})
        return httpx.Response(
            200,
            text=_bandcamp_page('<meta property="og:title" content="Song Title, by Artist Name">'),
        )

    handler, calls = _recording_handler(route)
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/a")
    assert song.isrc == "USEM38600088"
    bandcamp_calls = [c for c in calls if c.url.host.endswith("bandcamp.com")]
    assert len(bandcamp_calls) == 4  # _MAX_REDIRECT_HOPS (3) + the final page


async def test_bandcamp_redirect_loop_exhausts_hops_and_is_not_found():
    # Same-family redirects forever: give up after the hop budget, not-found.
    def route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "https://coolband.bandcamp.com/track/x"})

    handler, calls = _recording_handler(route)
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://coolband.bandcamp.com/track/x")
    assert len(calls) == 4  # _MAX_REDIRECT_HOPS (3) + 1 initial fetch, then stop


async def test_bandcamp_relative_redirect_location_resolves():
    # A relative Location resolves against the current URL and stays on-host.
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.deezer.com":
            return httpx.Response(200, json=_DEEZER_SEARCH_HIT)
        if request.url.path == "/track/old-slug":
            return httpx.Response(302, headers={"Location": "/track/new-slug"})
        return httpx.Response(
            200,
            text=_bandcamp_page('<meta property="og:title" content="Song Title, by Artist Name">'),
        )

    handler, calls = _recording_handler(route)
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/old-slug")
    assert song.isrc == "USEM38600088"
    assert calls[1].url.path == "/track/new-slug"
    assert calls[1].url.host == "coolband.bandcamp.com"


async def test_bandcamp_oversized_body_is_truncated_but_still_resolves():
    # og:title sits in <head>; a body padded past the 1 MiB cap must not break
    # resolution (the read is truncated, not buffered or failed).
    page = _bandcamp_page('<meta property="og:title" content="Song Title, by Artist Name">') + (
        "x" * (1 << 20)
    )
    handler = _router(bandcamp=lambda r: httpx.Response(200, text=page))
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/big")
    assert song.isrc == "USEM38600088"


async def test_bandcamp_data_property_meta_cannot_spoof_og_title():
    # data-property="og:title" is NOT property="og:title" — a decoy tag before
    # the real one must not win the extraction.
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok(
            '<meta data-property="og:title" content="Wrong Title, by Wrong Artist">'
            '<meta property="og:title" content="Song Title, by Artist Name">'
        ),
    )
    await _resolver(handler).resolve("https://coolband.bandcamp.com/track/x")
    assert 'track:"Song Title"' in seen["q"]
    assert 'artist:"Artist Name"' in seen["q"]


async def test_bandcamp_data_content_attribute_cannot_spoof_content():
    # Inside the real og:title tag, data-content= must not shadow content=.
    seen: dict[str, str] = {}
    handler = _router(
        search=_search_spy(seen),
        bandcamp=_bandcamp_ok(
            '<meta data-content="Wrong Title, by Wrong Artist"'
            ' property="og:title" content="Song Title, by Artist Name">'
        ),
    )
    await _resolver(handler).resolve("https://coolband.bandcamp.com/track/x")
    assert 'track:"Song Title"' in seen["q"]
    assert 'artist:"Artist Name"' in seen["q"]


async def test_bandcamp_page_without_og_title_is_not_found():
    handler = _router(bandcamp=lambda r: httpx.Response(200, text="<html><head></head></html>"))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/mystery")


async def test_bandcamp_empty_og_title_is_not_found():
    handler = _router(bandcamp=_bandcamp_ok('<meta property="og:title" content="">'))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/mystery")


async def test_bandcamp_non_track_url_is_invalid():
    with pytest.raises(InvalidSongURLError):
        await _resolver(_router()).resolve("https://artist.bandcamp.com/album/whatever")


async def test_bandcamp_page_404_is_not_found():
    handler = _router(bandcamp=lambda r: httpx.Response(404))
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/gone")


async def test_bandcamp_timeout_maps_to_resolver_timeout():
    def bandcamp(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    handler = _router(bandcamp=bandcamp)
    with pytest.raises(ResolverTimeoutError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/slow")


async def test_bandcamp_server_error_maps_to_unavailable():
    handler = _router(bandcamp=lambda r: httpx.Response(503))
    with pytest.raises(ResolverUnavailableError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/down")


async def test_bandcamp_rate_limit_maps_to_resolver_rate_limit():
    handler = _router(bandcamp=lambda r: httpx.Response(429))
    with pytest.raises(ResolverRateLimitError):
        await _resolver(handler).resolve("https://x.bandcamp.com/track/busy")


# --------------------------------------------------------------------------- #
# Bandcamp numeric track id (MYS-201, for the MYS-204 embedded player)
# --------------------------------------------------------------------------- #

# A representative EmbeddedPlayer URL Bandcamp puts in og:video / twitter:player.
_EMBED = "https://bandcamp.com/EmbeddedPlayer/v=2/track={id}/size=large/tracklist=false/"


def _tralbum(blob: str) -> str:
    """A data-tralbum element whose JSON is entity-escaped inside the (double-
    quoted) attribute, exactly as Bandcamp server-renders it."""
    escaped = blob.replace('"', "&quot;")
    return f'<div data-tralbum="{escaped}"></div>'


def test_bandcamp_track_id_from_og_video_embed_meta():
    page = _bandcamp_page(f'<meta property="og:video" content="{_EMBED.format(id="123456789")}">')
    assert _bandcamp_track_id(page) == "123456789"


def test_bandcamp_track_id_from_twitter_player_meta():
    page = _bandcamp_page(f'<meta name="twitter:player" content="{_EMBED.format(id="987654321")}">')
    assert _bandcamp_track_id(page) == "987654321"


def test_bandcamp_track_id_falls_back_to_tralbum_trackinfo_over_album_id():
    # No embed meta: read the FIRST trackinfo id, not the album_id that precedes it.
    page = _bandcamp_page(_tralbum('{"album_id":999,"trackinfo":[{"id":555444,"title":"x"}]}'))
    assert _bandcamp_track_id(page) == "555444"


def test_bandcamp_track_id_prefers_embed_over_tralbum():
    page = _bandcamp_page(
        f'<meta property="og:video" content="{_EMBED.format(id="111")}">'
        + _tralbum('{"trackinfo":[{"id":222}]}')
    )
    assert _bandcamp_track_id(page) == "111"


def test_bandcamp_track_id_none_when_neither_source_present():
    page = _bandcamp_page('<meta property="og:title" content="Song, by Artist">')
    assert _bandcamp_track_id(page) is None


def test_bandcamp_track_id_non_digit_embed_not_captured():
    # track=<non-digits>: the id regex requires digits, so nothing is captured.
    page = _bandcamp_page('<meta property="og:video" content="https://bandcamp.com/E/track=abc/">')
    assert _bandcamp_track_id(page) is None


def test_bandcamp_track_id_overlong_is_rejected():
    # A run longer than 20 digits fails the defensive length bound -> None.
    embed = _EMBED.format(id="1" * 21)
    page = _bandcamp_page(f'<meta property="og:video" content="{embed}">')
    assert _bandcamp_track_id(page) is None


async def test_bandcamp_catalog_hit_carries_track_id():
    # A catalog match keeps the canonical Deezer identity AND the Bandcamp id.
    handler = _router(
        bandcamp=_bandcamp_ok(
            '<meta property="og:title" content="Song Title, by Artist Name">'
            f'<meta property="og:video" content="{_EMBED.format(id="424242")}">'
        )
    )
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/song")
    assert song.isrc == "USEM38600088"  # canonical identity from Deezer
    assert song.bandcamp_track_id == "424242"


async def test_bandcamp_source_only_carries_track_id():
    handler = _router(
        search=_EMPTY_SEARCH,
        bandcamp=_bandcamp_ok(
            '<meta property="og:title" content="Bedroom Demo, by Cool Band">'
            f'<meta property="og:video" content="{_EMBED.format(id="7777")}">'
        ),
    )
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/bedroom-demo")
    assert song.source == "bandcamp"
    assert song.isrc is None
    assert song.bandcamp_track_id == "7777"


async def test_bandcamp_resolve_unaffected_when_no_track_id():
    # A page without an embed/tralbum id still resolves; the id is just None.
    handler = _router(
        bandcamp=_bandcamp_ok('<meta property="og:title" content="Song Title, by Artist Name">')
    )
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/song")
    assert song.isrc == "USEM38600088"
    assert song.bandcamp_track_id is None


async def test_non_bandcamp_resolves_have_no_track_id():
    # YouTube and direct Deezer paths never set a Bandcamp id.
    yt = await _resolver(
        _router(youtube=lambda r: httpx.Response(200, json={"title": "American Pie"}))
    ).resolve("https://youtu.be/PRpiBpDy7MQ")
    assert yt.bandcamp_track_id is None
    dz = await _resolver(_router()).resolve("https://www.deezer.com/track/3156285")
    assert dz.bandcamp_track_id is None


# --------------------------------------------------------------------------- #
# Dispatch + error mapping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://x", "spotify:track:2"])
async def test_invalid_url_raises_before_any_request(bad):
    def handler(_request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP should be called for an invalid URL")

    with pytest.raises(InvalidSongURLError):
        await _resolver(handler).resolve(bad)


async def test_unknown_host_is_not_found():
    with pytest.raises(SongNotFoundError):
        await _resolver(_router()).resolve("https://example.com/track/1")


async def test_no_search_match_is_not_found():
    handler = _router(
        spotify=lambda r: httpx.Response(200, json={"title": "obscure"}),
        search=lambda r: httpx.Response(200, json={"data": [], "total": 0}),
    )
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://open.spotify.com/track/abc")


async def test_rate_limit_maps_to_resolver_rate_limit():
    handler = _router(track=lambda r: httpx.Response(429))
    with pytest.raises(ResolverRateLimitError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_timeout_maps_to_resolver_timeout():
    def track(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    handler = _router(track=track)
    with pytest.raises(ResolverTimeoutError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_server_error_maps_to_unavailable():
    handler = _router(track=lambda r: httpx.Response(503))
    with pytest.raises(ResolverUnavailableError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


async def test_transport_error_maps_to_unavailable():
    def track(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    handler = _router(track=track)
    with pytest.raises(ResolverUnavailableError):
        await _resolver(handler).resolve("https://www.deezer.com/track/1")


# --------------------------------------------------------------------------- #
# Source-only fallback (MYS-201) — a genuine catalog miss returns a source
# identity keyed on the exact page; an upstream *error* still raises.
# --------------------------------------------------------------------------- #

_EMPTY_SEARCH = lambda r: httpx.Response(200, json={"data": [], "total": 0})  # noqa: E731


async def test_youtube_no_catalog_match_returns_source_identity():
    handler = _router(
        search=_EMPTY_SEARCH,
        youtube=lambda r: httpx.Response(
            200, json={"title": "Bedroom Demo", "author_name": "Nobody"}
        ),
    )
    song = await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")
    # No ISRC: identified by the exact video id instead, no fuzzy substitution.
    assert song.isrc is None
    assert song.source == "youtube"
    assert song.source_key == "youtube:PRpiBpDy7MQ"
    assert song.source_url == "https://www.youtube.com/watch?v=PRpiBpDy7MQ"


async def test_bandcamp_no_catalog_match_returns_source_identity():
    handler = _router(
        search=_EMPTY_SEARCH,
        bandcamp=_bandcamp_ok('<meta property="og:title" content="Bedroom Demo, by Cool Band">'),
    )
    song = await _resolver(handler).resolve("https://coolband.bandcamp.com/track/bedroom-demo")
    assert song.isrc is None
    assert song.source == "bandcamp"
    assert song.source_key == "bandcamp:coolband/bedroom-demo"
    assert song.source_url == "https://coolband.bandcamp.com/track/bedroom-demo"
    # The og:title still supplies display metadata, even without a catalog match.
    assert song.title == "Bedroom Demo"
    assert song.artist == "Cool Band"


async def test_bandcamp_apex_host_no_match_cannot_form_key_is_not_found():
    # bandcamp.com (no artist subdomain) can't reconstruct an {artist}/{track}
    # key, so a genuine miss there is simply not-found, never a bad guess.
    handler = _router(
        search=_EMPTY_SEARCH,
        bandcamp=_bandcamp_ok('<meta property="og:title" content="Bedroom Demo, by Cool Band">'),
    )
    with pytest.raises(SongNotFoundError):
        await _resolver(handler).resolve("https://bandcamp.com/track/bedroom-demo")


@pytest.mark.parametrize(
    ("search_response", "expected"),
    [
        # Deezer signals a quota/rate limit as HTTP 200 + error code 4.
        (
            lambda r: httpx.Response(200, json={"error": {"code": 4, "message": "quota"}}),
            ResolverRateLimitError,
        ),
        (lambda r: httpx.Response(503), ResolverUnavailableError),
    ],
)
async def test_youtube_source_fallback_not_triggered_on_upstream_error(search_response, expected):
    # A broken Deezer lookup must raise (mapped to 429/502), NOT be mistaken for a
    # catalog miss and silently downgraded to a source-only track.
    handler = _router(
        search=search_response,
        youtube=lambda r: httpx.Response(200, json={"title": "Bedroom Demo"}),
    )
    with pytest.raises(expected):
        await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")


async def test_youtube_source_fallback_not_triggered_on_search_timeout():
    def search(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    handler = _router(
        search=search, youtube=lambda r: httpx.Response(200, json={"title": "Bedroom Demo"})
    )
    with pytest.raises(ResolverTimeoutError):
        await _resolver(handler).resolve("https://www.youtube.com/watch?v=PRpiBpDy7MQ")


# --------------------------------------------------------------------------- #
# _get_text pins follow_redirects=False per hop (SSRF guard, MYS-201 intent)
# --------------------------------------------------------------------------- #


def _redirect_recording_resolver(handler):
    """A resolver whose client records the ``follow_redirects`` value handed to
    every ``stream`` call, so a test can assert the manual redirect loop never
    delegates redirect-following to httpx."""
    seen: list[object] = []

    def factory() -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)
        original_stream = client.stream

        def stream(method, url, **kwargs):
            seen.append(kwargs.get("follow_redirects"))
            return original_stream(method, url, **kwargs)

        client.stream = stream  # type: ignore[method-assign]
        return client

    return LinkResolver(client_factory=factory), seen


async def test_get_text_never_delegates_redirects_to_httpx():
    # A Bandcamp fetch that 301s to a valid on-family page must go through the
    # manual validated loop — every stream() call pins follow_redirects=False.
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.deezer.com":
            return httpx.Response(200, json=_DEEZER_SEARCH_HIT)
        if request.url.path == "/track/old-slug":
            return httpx.Response(
                301, headers={"Location": "https://coolband.bandcamp.com/track/new-slug"}
            )
        return httpx.Response(
            200,
            text=_bandcamp_page('<meta property="og:title" content="Song Title, by Artist Name">'),
        )

    resolver, seen = _redirect_recording_resolver(route)
    song = await resolver.resolve("https://coolband.bandcamp.com/track/old-slug")
    assert song.isrc == "USEM38600088"
    # Two Bandcamp hops (the 301 and the final page); Deezer search uses _get_json,
    # not stream, so only the page fetches are recorded here.
    assert seen == [False, False]
