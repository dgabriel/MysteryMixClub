"""Tests for the YouTube id retention sweep (MysteryMixClub-7a7x, ADR 0016).

YouTube API Services Developer Policies III.E.4(d) caps storage of
Non-Authorized Data at 30 calendar days. These tests pin the boundary, prove the
id is really gone (column *and* the watch URLs that embed it), and prove an
expired row becomes eligible for a refresh through the existing backfill path.

The job is called directly with an explicit ``now`` so the window is
deterministic.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.jobs.expire_youtube_ids import RETENTION_DAYS, expire_stale_youtube_ids
from app.models.submission import Submission
from app.services.youtube_backfill import has_pending
from tests.test_spotify_routes import _seed_mix, _seed_user

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)

_WATCH_LINKS = {
    "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "youtubeMusic": "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    "deezer": "https://www.deezer.com/track/123",
}


async def _add(
    db_session,
    mix_id,
    user_id,
    *,
    age_days: float,
    video_id: str | None = "dQw4w9WgXcQ",
    source_key: str | None = None,
    platform_links: dict | None = None,
    title: str = "Marquee Moon",
) -> Submission:
    submission = Submission(
        mix_id=mix_id,
        user_id=user_id,
        isrc=None if source_key else f"I-{title}",
        source_key=source_key,
        title=title,
        artist="Television",
        platform_links=platform_links if platform_links is not None else dict(_WATCH_LINKS),
        youtube_video_id=video_id,
        youtube_lookup_attempted_at=NOW - timedelta(days=age_days),
    )
    db_session.add(submission)
    await db_session.commit()
    await db_session.refresh(submission)
    return submission


async def test_expires_an_id_past_the_retention_window(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 1)

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 1

    await db_session.refresh(sub)
    assert sub.youtube_video_id is None


async def test_keeps_an_id_inside_the_window(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS - 1)

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 0

    await db_session.refresh(sub)
    assert sub.youtube_video_id == "dQw4w9WgXcQ"


async def test_watch_urls_are_rewritten_so_the_id_is_really_gone(db_session):
    """Clearing the column alone would only relocate the data.

    The assembled youtube/youtubeMusic links are exact watch?v=<id> URLs, so
    they carry the very id being expired.
    """
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 1)

    await expire_stale_youtube_ids(db_session, now=NOW)

    await db_session.refresh(sub)
    links = sub.platform_links
    assert "dQw4w9WgXcQ" not in str(links)  # the id survives nowhere
    assert links["youtube"] == (
        "https://www.youtube.com/results?search_query=Marquee%20Moon%20Television"
    )
    assert links["youtubeMusic"] == (
        "https://music.youtube.com/search?q=Marquee%20Moon%20Television"
    )
    # Every other platform's link is untouched — only YouTube's derived from it.
    assert links["deezer"] == "https://www.deezer.com/track/123"


async def test_expired_row_becomes_eligible_for_refresh(db_session):
    # The refresh arm of "delete or refresh": resetting to never-attempted is
    # what lets the existing enqueue-on-read path (ADR 0015) re-resolve it.
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 1)

    assert await has_pending(db_session, mix_.id) is False  # resolved, nothing to do
    await expire_stale_youtube_ids(db_session, now=NOW)

    await db_session.refresh(sub)
    assert sub.youtube_lookup_attempted_at is None
    assert await has_pending(db_session, mix_.id) is True


async def test_source_only_track_is_never_expired(db_session):
    """A youtube:<id> source_key comes from the URL the submitter pasted, not
    from the API, so it isn't API Data — and it's the track's only identity."""
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(
        db_session,
        mix_.id,
        organizer.id,
        age_days=RETENTION_DAYS + 400,
        source_key="youtube:dQw4w9WgXcQ",
    )

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 0

    await db_session.refresh(sub)
    assert sub.youtube_video_id == "dQw4w9WgXcQ"
    assert sub.source_key == "youtube:dQw4w9WgXcQ"


async def test_recorded_miss_is_left_alone(db_session):
    # A row with no id stores no API Data, so there is nothing to expire. Leaving
    # its tombstone intact is what stops the backfill re-asking forever (ADR 0015).
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(
        db_session,
        mix_.id,
        organizer.id,
        age_days=RETENTION_DAYS + 10,
        video_id=None,
        platform_links={},
    )

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 0

    await db_session.refresh(sub)
    assert sub.youtube_lookup_attempted_at is not None


async def test_expiry_does_not_depend_on_a_refresh_succeeding(db_session):
    """Deletion is unconditional.

    If expiry were gated on re-resolving, a spent quota or a YouTube outage
    would silently park us past the limit — the exact failure mode ADR 0015
    already had to guard against once.
    """
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    sub = await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 1)

    # No resolver is passed or reachable anywhere in this job's signature.
    assert await expire_stale_youtube_ids(db_session, now=NOW) == 1
    await db_session.refresh(sub)
    assert sub.youtube_video_id is None


async def test_sweep_is_idempotent(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 1)

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 1
    assert await expire_stale_youtube_ids(db_session, now=NOW) == 0


async def test_expires_across_many_rows_and_leaves_fresh_ones(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    other = await _seed_user(db_session, "x@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add(db_session, mix_.id, organizer.id, age_days=RETENTION_DAYS + 5, title="Old One")
    await _add(db_session, mix_.id, other.id, age_days=RETENTION_DAYS + 90, title="Old Two")
    await _add(db_session, mix_.id, other.id, age_days=1, title="Fresh")

    assert await expire_stale_youtube_ids(db_session, now=NOW) == 2

    rows = {
        s.title: s
        for s in await db_session.scalars(select(Submission).where(Submission.mix_id == mix_.id))
    }
    assert rows["Old One"].youtube_video_id is None
    assert rows["Old Two"].youtube_video_id is None
    assert rows["Fresh"].youtube_video_id == "dQw4w9WgXcQ"


async def test_retention_window_is_the_policy_number(db_session):
    # Lowering this is safe; raising it past 30 violates III.E.4(d).
    assert RETENTION_DAYS <= 30
