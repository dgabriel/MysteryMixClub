"""Tests for the YouTube video-id backfill service (MysteryMixClub-6jzl, ADR 0015).

The behaviour that matters here is the memoization: an attempt is recorded
whether or not it matched, so a miss is never re-asked. Before ADR 0015 a miss
left the row indistinguishable from "never tried", and every playlist read
re-ran the lookup forever.
"""

from sqlalchemy import select

from app.models.submission import Submission
from app.services.youtube_backfill import BackfillResult, backfill_mix, has_pending
from app.services.youtube_resolver import YouTubeLookup
from tests.test_spotify_routes import _add_submission, _seed_mix, _seed_user


class _StubYouTube:
    """``answered=True`` unless the title is listed in ``unreachable`` — which
    stands in for a quota 403 / timeout, where YouTube never answered at all."""

    def __init__(
        self,
        by_title: dict[str, str] | None = None,
        *,
        unreachable: set[str] | None = None,
    ) -> None:
        self._by_title = by_title or {}
        self._unreachable = unreachable or set()
        self.calls: list[str] = []

    async def resolve(self, title: str, artist: str | None = None) -> YouTubeLookup:
        self.calls.append(title)
        if title in self._unreachable:
            return YouTubeLookup(video_id=None, answered=False)
        return YouTubeLookup(video_id=self._by_title.get(title), answered=True)


async def test_hit_is_cached_and_marked_attempted(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I", title="hit")

    youtube = _StubYouTube({"hit": "VID"})
    result = await backfill_mix(db_session, mix_.id, youtube)

    assert result == BackfillResult(hits=1, misses=0, unreachable=0)
    sub = await db_session.scalar(select(Submission).where(Submission.mix_id == mix_.id))
    assert sub.youtube_video_id == "VID"
    assert sub.youtube_lookup_attempted_at is not None


async def test_miss_is_marked_attempted_and_never_retried(db_session):
    """The whole point of the column: a miss must not come back."""
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I", title="nowhere")

    youtube = _StubYouTube({})  # resolves nothing
    result = await backfill_mix(db_session, mix_.id, youtube)

    assert result == BackfillResult(hits=0, misses=1, unreachable=0)
    sub = await db_session.scalar(select(Submission).where(Submission.mix_id == mix_.id))
    assert sub.youtube_video_id is None
    assert sub.youtube_lookup_attempted_at is not None

    # Second pass: the row is no longer pending, so nothing is asked again.
    assert await has_pending(db_session, mix_.id) is False
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(0, 0, 0)
    assert youtube.calls == ["nowhere"]  # exactly one lookup, ever


async def test_already_resolved_rows_are_skipped(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(
        db_session, mix_.id, organizer.id, isrc="I", title="cached", youtube_video_id="OLD"
    )

    youtube = _StubYouTube({"cached": "SHOULD_NOT_BE_USED"})
    assert await has_pending(db_session, mix_.id) is False
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(0, 0, 0)
    assert youtube.calls == []


async def test_source_only_rows_are_never_fuzzy_matched(db_session):
    """MYS-201: a bandcamp: row must never be linked to a *guessed* video, and a
    youtube: row already carries its exact id — neither is ever looked up."""
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(
        db_session,
        mix_.id,
        organizer.id,
        isrc=None,
        source_key="bandcamp:artist/track",
        title="source only",
    )

    youtube = _StubYouTube({"source only": "GUESSED"})
    assert await has_pending(db_session, mix_.id) is False
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(0, 0, 0)
    assert youtube.calls == []


async def test_mixed_batch_reports_hits_and_misses(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    other = await _seed_user(db_session, "x@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I0", title="found")
    await _add_submission(db_session, mix_.id, other.id, isrc="I1", title="lost")

    youtube = _StubYouTube({"found": "VID"})
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(1, 1, 0)
    assert sorted(youtube.calls) == ["found", "lost"]

    # Both rows are stamped, so the batch drains in one pass regardless of outcome.
    subs = list(await db_session.scalars(select(Submission).where(Submission.mix_id == mix_.id)))
    assert all(s.youtube_lookup_attempted_at is not None for s in subs)
    assert await has_pending(db_session, mix_.id) is False


async def test_empty_mix_is_a_noop(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)

    youtube = _StubYouTube({})
    assert await has_pending(db_session, mix_.id) is False
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(0, 0, 0)
    assert youtube.calls == []


async def test_unreachable_track_is_left_pending_not_written_off(db_session):
    """Regression for the failure this design hit on its first real run.

    The quota was spent, so YouTube 403'd on half the batch. Flattening that to
    "no match" stamped ten resolvable tracks as permanently unmatched. An
    unanswered lookup must leave the row exactly as it found it.
    """
    organizer = await _seed_user(db_session, "o@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I", title="quota blocked")

    youtube = _StubYouTube({}, unreachable={"quota blocked"})
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(0, 0, 1)

    sub = await db_session.scalar(select(Submission).where(Submission.mix_id == mix_.id))
    assert sub.youtube_video_id is None
    assert sub.youtube_lookup_attempted_at is None  # untouched — not an answer

    # Still pending, so a later job retries it — and now succeeds.
    assert await has_pending(db_session, mix_.id) is True
    recovered = _StubYouTube({"quota blocked": "VID"})
    assert await backfill_mix(db_session, mix_.id, recovered) == BackfillResult(1, 0, 0)
    await db_session.refresh(sub)
    assert sub.youtube_video_id == "VID"


async def test_partial_outage_records_only_the_answered_tracks(db_session):
    # The exact shape of the real incident: some answered, some 403'd. Only the
    # answered ones may be stamped; the rest stay eligible for the next pass.
    organizer = await _seed_user(db_session, "o@example.com")
    other = await _seed_user(db_session, "x@example.com")
    mix_ = await _seed_mix(db_session, organizer)
    await _add_submission(db_session, mix_.id, organizer.id, isrc="I0", title="answered")
    await _add_submission(db_session, mix_.id, other.id, isrc="I1", title="blocked")

    youtube = _StubYouTube({"answered": "VID"}, unreachable={"blocked"})
    assert await backfill_mix(db_session, mix_.id, youtube) == BackfillResult(1, 0, 1)

    subs = {
        s.title: s
        for s in await db_session.scalars(select(Submission).where(Submission.mix_id == mix_.id))
    }
    assert subs["answered"].youtube_lookup_attempted_at is not None
    assert subs["blocked"].youtube_lookup_attempted_at is None
    assert await has_pending(db_session, mix_.id) is True
