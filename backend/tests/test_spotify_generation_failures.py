"""Spotify playlist generation must not fail silently (MysteryMixClub-gz6c).

Prod showed "1 of 16 songs" with a real 1-track playlist and nothing in any log:
every lookup failure was swallowed as "no match", and the job was marked complete.
These pin the replacement behavior: a lookup that ERRORED is told apart from one
that cleanly MISSED, a run dominated by errors fails before it can overwrite a good
playlist, a 429 gets one honored retry then stops, and the run leaves a summary.
"""

import logging

import pytest
from sqlalchemy import select

from app.models.submission import Submission
from app.services import spotify_playlist_generation as generation
from app.services.spotify_client import IsrcLookup, SpotifyApiError
from tests.test_spotify_routes import (
    FakeSpotifyClient,
    _add_submission,
    _generate,
    _seed_member,
    _seed_mix,
    _seed_shared_account,
    _seed_user,
)

_FORBIDDEN = IsrcLookup("error", status=403, reason="http")
_SERVER_ERROR = IsrcLookup("error", status=503, reason="http")


def _hit(n: int) -> IsrcLookup:
    return IsrcLookup("hit", uri=f"spotify:track:{n}")


async def _mix_with_tracks(db_session, count: int):
    """A mix with ``count`` ISRC-backed submissions ``I-0`` .. ``I-{count-1}``."""
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _seed_shared_account(db_session)
    authors = [organizer] + [
        await _seed_member(db_session, mix_, f"m{i}@example.com") for i in range(1, count)
    ]
    for i, author in enumerate(authors):
        await _add_submission(db_session, mix_.id, author.id, isrc=f"I-{i}", title=f"song {i}")
    return mix_


@pytest.fixture
def no_wait(monkeypatch):
    """Skip real sleeps and record what would have been waited."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(generation, "_sleep", fake_sleep)
    return waits


class _LogCollector(logging.Handler):
    """Not ``caplog``: ``app/main.py`` sets ``propagate = False`` on the ``app``
    logger, so records never reach the root logger caplog listens on."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int | None = None) -> list[str]:
        return [r.getMessage() for r in self.records if level is None or r.levelno == level]


@pytest.fixture
def gen_logs():
    handler = _LogCollector()
    logger = generation.logger
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


# --------------------------------------------------------------------------- #
# Errors are not misses
# --------------------------------------------------------------------------- #


async def test_every_lookup_erroring_fails_the_job_and_leaves_the_playlist_alone(db_session):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(lookup_overrides={f"I-{i}": _FORBIDDEN for i in range(4)})

    with pytest.raises(SpotifyApiError) as excinfo:
        await _generate(db_session, mix_, fake)

    assert "4 of 4" in str(excinfo.value)
    assert "http-403 x4" in str(excinfo.value)
    # Nothing was written to Spotify: a truncated set must never replace a good one.
    assert fake.created is None
    assert fake.added == []
    assert fake.replaced is None


async def test_a_failed_run_keeps_the_uris_it_did_resolve(db_session):
    # 1 hit + 3 errors = 75% errored: fails, but the hit is persisted so a re-run only
    # has to resolve the remainder.
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(
        lookup_overrides={
            "I-0": _hit(0),
            "I-1": _SERVER_ERROR,
            "I-2": _SERVER_ERROR,
            "I-3": _SERVER_ERROR,
        }
    )

    mix_id = mix_.id  # capture before expire_all(): an expired ORM attr raises MissingGreenlet
    with pytest.raises(SpotifyApiError):
        await _generate(db_session, mix_, fake)

    db_session.expire_all()
    rows = {
        s.isrc: s.spotify_track_uri
        for s in await db_session.scalars(select(Submission).where(Submission.mix_id == mix_id))
    }
    assert rows["I-0"] == "spotify:track:0"
    assert rows["I-1"] is None
    assert fake.created is None


async def test_a_minority_of_errors_still_publishes_and_reports_them_unmatched(db_session):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(
        lookup_overrides={"I-0": _hit(0), "I-1": _hit(1), "I-2": _hit(2), "I-3": _SERVER_ERROR}
    )

    result = await _generate(db_session, mix_, fake)  # 25% errored: no raise

    assert result.track_count == 3
    assert [u.title for u in result.unmatched] == ["song 3"]
    assert fake.created is not None


async def test_clean_misses_are_a_catalog_gap_and_never_fail_the_job(db_session):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient()  # every ISRC cleanly not on Spotify

    result = await _generate(db_session, mix_, fake)

    assert result.track_count == 0
    assert result.playlist_url is None
    assert len(result.unmatched) == 4


async def test_exactly_half_errored_is_a_failure(db_session):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(
        lookup_overrides={"I-0": _hit(0), "I-1": _hit(1), "I-2": _FORBIDDEN, "I-3": _FORBIDDEN}
    )
    with pytest.raises(SpotifyApiError):
        await _generate(db_session, mix_, fake)


# --------------------------------------------------------------------------- #
# The app token
# --------------------------------------------------------------------------- #


class _NoTokenSpotify(FakeSpotifyClient):
    async def app_access_token(self):
        return None


async def test_a_missing_app_token_is_an_error_not_a_silent_skip(db_session):
    mix_ = await _mix_with_tracks(db_session, 3)
    fake = _NoTokenSpotify(isrc_map={"I-0": "spotify:track:0"})

    with pytest.raises(SpotifyApiError) as excinfo:
        await _generate(db_session, mix_, fake)

    assert "no-app-token x3" in str(excinfo.value)
    assert fake.searched_isrcs == []  # nothing to ask with, so nothing was asked
    assert fake.created is None


async def test_already_cached_uris_need_no_token_and_no_lookup(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _seed_shared_account(db_session)
    await _add_submission(
        db_session,
        mix_.id,
        organizer.id,
        isrc="I-0",
        title="cached",
        spotify_track_uri="spotify:track:cached",
    )
    fake = _NoTokenSpotify()

    result = await _generate(db_session, mix_, fake)  # nothing attempted, so no failure

    assert result.track_count == 1
    assert fake.searched_isrcs == []
    assert fake.added == ["spotify:track:cached"]


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


async def test_a_429_is_retried_once_after_the_wait_spotify_asked_for(db_session, no_wait):
    mix_ = await _mix_with_tracks(db_session, 1)
    fake = FakeSpotifyClient(
        lookup_overrides={
            "I-0": [IsrcLookup("error", status=429, reason="http", retry_after=2.0), _hit(0)]
        }
    )

    result = await _generate(db_session, mix_, fake)

    assert no_wait == [2.0]
    assert fake.searched_isrcs == ["I-0", "I-0"]
    assert result.track_count == 1


async def test_a_huge_retry_after_is_capped(db_session, no_wait):
    mix_ = await _mix_with_tracks(db_session, 1)
    fake = FakeSpotifyClient(
        lookup_overrides={
            "I-0": [IsrcLookup("error", status=429, reason="http", retry_after=3600.0), _hit(0)]
        }
    )
    await _generate(db_session, mix_, fake)
    assert no_wait == [10.0]


async def test_a_429_without_retry_after_waits_a_default(db_session, no_wait):
    mix_ = await _mix_with_tracks(db_session, 1)
    fake = FakeSpotifyClient(
        lookup_overrides={"I-0": [IsrcLookup("error", status=429, reason="http"), _hit(0)]}
    )
    await _generate(db_session, mix_, fake)
    assert no_wait == [1.0]


async def test_persistent_throttling_stops_further_lookups_and_fails_the_job(db_session, no_wait):
    mix_ = await _mix_with_tracks(db_session, 5)
    throttled = IsrcLookup("error", status=429, reason="http", retry_after=0.0)
    # Every ISRC throttles (the generator shuffles, so which one goes first is not
    # ours to pick) and the 429 repeats on the retry.
    fake = FakeSpotifyClient(lookup_overrides={f"I-{i}": throttled for i in range(5)})

    with pytest.raises(SpotifyApiError) as excinfo:
        await _generate(db_session, mix_, fake)

    # One track asked (twice: original + one retry), the other four never asked.
    assert len(fake.searched_isrcs) == 2
    assert fake.searched_isrcs[0] == fake.searched_isrcs[1]
    assert "http-429 x1" in str(excinfo.value)
    assert "skipped-after-429 x4" in str(excinfo.value)
    assert fake.created is None


# --------------------------------------------------------------------------- #
# Observability
# --------------------------------------------------------------------------- #


async def test_a_run_logs_a_summary_with_counts_and_failure_reasons(db_session, gen_logs):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(
        lookup_overrides={"I-0": _hit(0), "I-1": _hit(1), "I-2": _hit(2), "I-3": _SERVER_ERROR},
    )
    await _generate(db_session, mix_, fake)

    (summary,) = [m for m in gen_logs.messages(logging.INFO) if "spotify playlist for mix" in m]
    assert "4 submissions" in summary
    assert "0 already cached" in summary
    assert "3 newly matched" in summary
    assert "0 not on spotify" in summary
    assert "1 lookup errors" in summary
    assert "http-503 x1" in summary


async def test_a_clean_run_summary_has_no_error_clause(db_session, gen_logs):
    mix_ = await _mix_with_tracks(db_session, 2)
    fake = FakeSpotifyClient(lookup_overrides={"I-0": _hit(0), "I-1": _hit(1)})
    await _generate(db_session, mix_, fake)

    (summary,) = [m for m in gen_logs.messages(logging.INFO) if "spotify playlist for mix" in m]
    assert "0 lookup errors" in summary
    assert "(" not in summary


async def test_each_distinct_failure_is_warned_once_and_never_names_the_track(db_session, gen_logs):
    mix_ = await _mix_with_tracks(db_session, 4)
    fake = FakeSpotifyClient(
        lookup_overrides={
            "I-0": _SERVER_ERROR,
            "I-1": _SERVER_ERROR,
            "I-2": IsrcLookup("error", reason="timeout"),
            "I-3": _hit(3),
        },
    )
    with pytest.raises(SpotifyApiError):
        await _generate(db_session, mix_, fake)

    warnings = [m for m in gen_logs.messages(logging.WARNING) if "lookup failed" in m]
    # Submissions are shuffled by a seed derived from the (random) mix id, so which
    # distinct failure is seen first varies per run; each must appear exactly once.
    assert sorted(warnings) == [
        "spotify ISRC lookup failed (http-503)",
        "spotify ISRC lookup failed (timeout)",
    ]
    everything = "\n".join(gen_logs.messages())
    for secret in ("I-0", "I-1", "song 0", "song 1"):
        assert secret not in everything


async def test_a_failed_cache_write_is_logged_and_the_playlist_is_still_built(
    db_session, gen_logs, monkeypatch
):
    mix_ = await _mix_with_tracks(db_session, 2)
    fake = FakeSpotifyClient(lookup_overrides={"I-0": _hit(0), "I-1": _hit(1)})

    real_commit = db_session.commit
    calls = {"n": 0}

    async def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db went away")
        await real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)
    result = await _generate(db_session, mix_, fake)

    assert result.track_count == 2  # built from memory regardless
    assert any(
        "could not persist newly resolved spotify track URIs" in m for m in gen_logs.messages()
    )
