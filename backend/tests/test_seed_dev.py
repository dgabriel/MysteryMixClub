"""Tests for MysteryMixClub-t2ai: seed_dev.py's YouTube-quota fix.

Doesn't exercise seed()/wipe_clubs() end to end -- seed_dev.py is a
destructive local-dev script (wipes every club in whatever DATABASE_URL
points at) with no established pattern in this repo for sandboxing that
inside the shared test suite. Instead, these test the actual property the
ticket cares about directly: every catalogue submission make_submission
builds is already "resolved" by youtube_backfill's own pending-row
definition, and source-only submissions are correctly left alone.

make_submission/make_source_submission only read `.id` off their mix/user
arguments, so plain stand-ins are enough -- no DB, no real Mix/User rows.
"""

from types import SimpleNamespace
from uuid import uuid4

from scripts.seed_dev import SONGS, SOURCE_ONLY, make_source_submission, make_submission

_MIX = SimpleNamespace(id=uuid4())
_USER = SimpleNamespace(id=uuid4())


def _is_pending_backfill(submission) -> bool:
    """Mirrors youtube_backfill.pending_submissions_stmt's condition for a
    single in-memory row (no DB round trip): pending only when ALL three are
    true. Setting youtube_video_id alone already breaks the AND."""
    return (
        submission.youtube_video_id is None
        and submission.youtube_lookup_attempted_at is None
        and submission.source_key is None
    )


def test_every_song_carries_a_youtube_video_id():
    for song in SONGS:
        assert song.get("youtube_video_id"), f"missing youtube_video_id: {song['title']!r}"


def test_make_submission_leaves_nothing_pending_backfill():
    for song in SONGS:
        submission = make_submission(_MIX, _USER, song)
        assert not _is_pending_backfill(submission), f"still pending: {song['title']!r}"
        assert submission.youtube_video_id == song["youtube_video_id"]
        assert submission.youtube_lookup_attempted_at is not None


def test_make_submission_youtube_links_match_the_stamped_video_id():
    # Internal consistency: platform_links should show the same video the
    # submission is now stamped as resolved to, not a stale search deep link.
    for song in SONGS:
        submission = make_submission(_MIX, _USER, song)
        video_id = submission.youtube_video_id
        assert submission.platform_links["youtube"] == f"https://www.youtube.com/watch?v={video_id}"
        assert (
            submission.platform_links["youtubeMusic"]
            == f"https://music.youtube.com/watch?v={video_id}"
        )


def test_make_source_submission_stays_unresolved():
    # Acceptance criterion #4 (MysteryMixClub-t2ai): the two source-only
    # tracks must keep source_key and stay unresolved, as production would --
    # a source-only row is never fuzzy-matched against YouTube (MYS-201).
    for track in SOURCE_ONLY:
        submission = make_source_submission(_MIX, _USER, track)
        assert submission.youtube_video_id is None
        assert submission.youtube_lookup_attempted_at is None
        assert submission.source_key == track["source_key"]
        assert _is_pending_backfill(submission) is False  # source_key excludes it too
