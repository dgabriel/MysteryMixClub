"""Tests for the admin metrics surface.

MysteryMixClub-etz7.1 — GET /api/v1/admin/metrics: aggregate-only platform
snapshot (technical-design §10 — no user-level tracking), gated by the same
get_platform_admin dependency as the rest of /admin. Covers authorization (401
unauthenticated, 403 authenticated non-admin), every aggregate field against
known seeded data, and the empty-platform edge case (all zeros, avg 0.0 rather
than a divide-by-zero).

MysteryMixClub-etz7.2 — GET /api/v1/admin/metrics/signups: daily signup counts
over a bounded window. Covers the same authorization gate, zero-filling of days
with no signups, ordering/window arithmetic, the `days` query bounds (422 rather
than a silent clamp), and UTC day-boundary bucketing.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote
from app.models.waitlist_entry import WaitlistEntry

ADMIN_EMAIL = "admin@example.com"
METRICS_URL = "/api/v1/admin/metrics"

EXPECTED_FIELDS = {
    "total_users",
    "total_clubs",
    "active_clubs",
    "complete_clubs",
    "total_mixes",
    "pending_mixes",
    "open_submission_mixes",
    "open_voting_mixes",
    "closed_mixes",
    "total_submissions",
    "avg_submissions_per_mix",
    "total_votes",
    "total_notes",
    "waitlist_total",
    "waitlist_pending",
    "waitlist_invited",
}


@pytest.fixture
def seed_admin_emails() -> str:
    return ADMIN_EMAIL


async def _seed_user(db_session, email: str, *, name: str = "User", deleted_at=None) -> User:
    user = User(email=email, display_name=name, deleted_at=deleted_at)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(db_session) -> User:
    return await _seed_user(db_session, ADMIN_EMAIL, name="Admin")


def _auth(user_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# ========================================================================== #
# Authorization
# ========================================================================== #


async def test_metrics_unauthenticated_returns_401(client, db_session):
    await _seed_admin(db_session)

    resp = await client.get(METRICS_URL)

    assert resp.status_code == 401, resp.text


async def test_metrics_non_admin_returns_403(client, db_session):
    plain = await _seed_user(db_session, "plain@example.com")

    resp = await client.get(METRICS_URL, headers=_auth(plain.id))

    assert resp.status_code == 403, resp.text


# ========================================================================== #
# Happy path — every aggregate against known seeded data
# ========================================================================== #


async def test_metrics_returns_all_aggregate_counts(client, db_session):
    admin = await _seed_admin(db_session)
    alice = await _seed_user(db_session, "alice@example.com", name="Alice")
    bob = await _seed_user(db_session, "bob@example.com", name="Bob")
    # Soft-deleted accounts are not live users and must not be counted.
    await _seed_user(
        db_session, "gone@example.com", name="Gone", deleted_at=datetime.now(timezone.utc)
    )

    active_club = Club(name="Active", organizer_id=alice.id, total_mixes=3, state="active")
    complete_club = Club(name="Complete", organizer_id=bob.id, total_mixes=1, state="complete")
    db_session.add_all([active_club, complete_club])
    await db_session.flush()

    pending_mix = Mix(club_id=active_club.id, mix_number=1, theme="t1", state="pending")
    open_sub_mix = Mix(club_id=active_club.id, mix_number=2, theme="t2", state="open_submission")
    open_vote_mix = Mix(club_id=active_club.id, mix_number=3, theme="t3", state="open_voting")
    closed_mix = Mix(club_id=complete_club.id, mix_number=1, theme="t4", state="closed")
    db_session.add_all([pending_mix, open_sub_mix, open_vote_mix, closed_mix])
    await db_session.flush()

    # 3 submissions spread over 2 distinct mixes -> avg 1.5.
    sub_a = Submission(
        mix_id=closed_mix.id,
        user_id=alice.id,
        isrc="USABC1234567",
        title="One",
        artist="A",
        participation_mode="playing",
    )
    sub_b = Submission(
        mix_id=closed_mix.id,
        user_id=bob.id,
        isrc="USABC7654321",
        title="Two",
        artist="B",
        participation_mode="playing",
    )
    sub_c = Submission(
        mix_id=open_vote_mix.id,
        user_id=alice.id,
        isrc="USABC1112223",
        title="Three",
        artist="C",
        participation_mode="playing",
    )
    db_session.add_all([sub_a, sub_b, sub_c])
    await db_session.flush()

    db_session.add_all(
        [
            Vote(mix_id=closed_mix.id, voter_id=alice.id, submission_id=sub_b.id),
            Vote(mix_id=closed_mix.id, voter_id=bob.id, submission_id=sub_a.id),
        ]
    )
    db_session.add(
        Note(mix_id=closed_mix.id, author_id=bob.id, submission_id=sub_a.id, body="nice")
    )
    db_session.add_all(
        [
            WaitlistEntry(email="w1@example.com"),
            WaitlistEntry(email="w2@example.com"),
            WaitlistEntry(
                email="w3@example.com",
                invited_at=datetime.now(timezone.utc),
                invited_by=admin.id,
            ),
        ]
    )
    await db_session.commit()

    admin_id = admin.id

    resp = await client.get(METRICS_URL, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == EXPECTED_FIELDS
    assert body == {
        "total_users": 3,  # admin + alice + bob; the soft-deleted account is excluded
        "total_clubs": 2,
        "active_clubs": 1,
        "complete_clubs": 1,
        "total_mixes": 4,
        "pending_mixes": 1,
        "open_submission_mixes": 1,
        "open_voting_mixes": 1,
        "closed_mixes": 1,
        "total_submissions": 3,
        "avg_submissions_per_mix": 1.5,
        "total_votes": 2,
        "total_notes": 1,
        "waitlist_total": 3,
        "waitlist_pending": 2,
        "waitlist_invited": 1,
    }


async def test_metrics_averages_over_mixes_that_received_submissions(client, db_session):
    # Mixes are auto-created up front, so the average is deliberately over
    # mixes that actually got a submission — two empty mixes must not drag it
    # down.
    admin = await _seed_admin(db_session)
    club = Club(name="C", organizer_id=admin.id, total_mixes=3, state="active")
    db_session.add(club)
    await db_session.flush()
    used = Mix(club_id=club.id, mix_number=1, theme="t", state="closed")
    db_session.add_all(
        [
            used,
            Mix(club_id=club.id, mix_number=2, theme="t", state="pending"),
            Mix(club_id=club.id, mix_number=3, theme="t", state="pending"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            Submission(
                mix_id=used.id,
                user_id=admin.id,
                isrc="USABC0000001",
                title="a",
                artist="a",
                participation_mode="playing",
            ),
            Submission(
                mix_id=used.id,
                user_id=admin.id,
                isrc="USABC0000002",
                title="b",
                artist="b",
                participation_mode="playing",
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get(METRICS_URL, headers=_auth(admin.id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_mixes"] == 3
    assert body["total_submissions"] == 2
    assert body["avg_submissions_per_mix"] == 2.0


# ========================================================================== #
# Edge case — empty platform
# ========================================================================== #


async def test_metrics_on_empty_platform_returns_zeros(client, db_session):
    # The admin account itself is the only row that must exist to make the
    # call; everything else is zero, and the average is 0.0 rather than a
    # divide-by-zero error.
    admin = await _seed_admin(db_session)

    resp = await client.get(METRICS_URL, headers=_auth(admin.id))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "total_users": 1,
        "total_clubs": 0,
        "active_clubs": 0,
        "complete_clubs": 0,
        "total_mixes": 0,
        "pending_mixes": 0,
        "open_submission_mixes": 0,
        "open_voting_mixes": 0,
        "closed_mixes": 0,
        "total_submissions": 0,
        "avg_submissions_per_mix": 0.0,
        "total_votes": 0,
        "total_notes": 0,
        "waitlist_total": 0,
        "waitlist_pending": 0,
        "waitlist_invited": 0,
    }


# ========================================================================== #
# MysteryMixClub-etz7.2 — GET /api/v1/admin/metrics/signups
# ========================================================================== #

SIGNUPS_URL = "/api/v1/admin/metrics/signups"

# Far enough back that the admin account never lands inside a test's window,
# even at the 365-day maximum, so bucket counts come only from seeded signups.
_ADMIN_AGE = timedelta(days=400)


async def _seed_user_at(db_session, email: str, created_at: datetime, *, deleted_at=None) -> User:
    user = User(email=email, display_name=email, created_at=created_at, deleted_at=deleted_at)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_old_admin(db_session) -> User:
    return await _seed_user_at(db_session, ADMIN_EMAIL, datetime.now(timezone.utc) - _ADMIN_AGE)


async def test_signup_trend_unauthenticated_returns_401(client, db_session):
    await _seed_admin(db_session)

    resp = await client.get(SIGNUPS_URL)

    assert resp.status_code == 401, resp.text


async def test_signup_trend_non_admin_returns_403(client, db_session):
    plain = await _seed_user(db_session, "plain@example.com")

    resp = await client.get(SIGNUPS_URL, headers=_auth(plain.id))

    assert resp.status_code == 403, resp.text


async def test_signup_trend_zero_fills_days_with_no_signups(client, db_session):
    # Window of 5 days with signups on days 0, 2 and 4 — the two empty days in
    # the middle must still come back, as count 0, so the series is continuous.
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id
    now = datetime.now(timezone.utc)

    await _seed_user_at(db_session, "d4a@example.com", now - timedelta(days=4))
    await _seed_user_at(db_session, "d4b@example.com", now - timedelta(days=4))
    await _seed_user_at(db_session, "d2@example.com", now - timedelta(days=2))
    await _seed_user_at(db_session, "d0a@example.com", now)
    await _seed_user_at(db_session, "d0b@example.com", now)
    await _seed_user_at(db_session, "d0c@example.com", now)

    resp = await client.get(SIGNUPS_URL, params={"days": 5}, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 5

    today = now.date()
    expected = [
        {"day": str(today - timedelta(days=4)), "count": 2},
        {"day": str(today - timedelta(days=3)), "count": 0},
        {"day": str(today - timedelta(days=2)), "count": 1},
        {"day": str(today - timedelta(days=1)), "count": 0},
        {"day": str(today), "count": 3},
    ]
    assert body["buckets"] == expected


async def test_signup_trend_buckets_are_ascending_and_end_today(client, db_session):
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id

    resp = await client.get(SIGNUPS_URL, params={"days": 7}, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    days = [b["day"] for b in resp.json()["buckets"]]
    assert len(days) == 7
    assert days == sorted(days)
    assert days[-1] == str(datetime.now(timezone.utc).date())


async def test_signup_trend_defaults_to_30_days(client, db_session):
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id

    resp = await client.get(SIGNUPS_URL, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 30
    assert len(body["buckets"]) == 30
    assert all(b["count"] == 0 for b in body["buckets"])


async def test_signup_trend_honours_explicit_days(client, db_session):
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id

    for days in (1, 5, 365):
        resp = await client.get(SIGNUPS_URL, params={"days": days}, headers=_auth(admin_id))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["days"] == days
        assert len(body["buckets"]) == days


@pytest.mark.parametrize("days", [0, -1, 366, 400, "abc"])
async def test_signup_trend_rejects_out_of_range_days(client, db_session, days):
    # Out-of-range windows are a 422, not a silent clamp and not a 500.
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id

    resp = await client.get(SIGNUPS_URL, params={"days": days}, headers=_auth(admin_id))

    assert resp.status_code == 422, resp.text


async def test_signup_trend_excludes_deleted_and_out_of_window_users(client, db_session):
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id
    now = datetime.now(timezone.utc)

    # Inside the 3-day window but soft-deleted.
    await _seed_user_at(db_session, "gone@example.com", now - timedelta(days=1), deleted_at=now)
    # Live, but signed up before the window opens.
    await _seed_user_at(db_session, "ancient@example.com", now - timedelta(days=4))
    await _seed_user_at(db_session, "live@example.com", now - timedelta(days=1))

    resp = await client.get(SIGNUPS_URL, params={"days": 3}, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    counts = [b["count"] for b in resp.json()["buckets"]]
    assert counts == [0, 1, 0]


async def test_signup_trend_buckets_by_utc_day_boundary(client, db_session):
    admin = await _seed_old_admin(db_session)
    admin_id = admin.id

    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    midnight = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)

    # First and last instant of yesterday UTC both belong to yesterday's
    # bucket; one microsecond earlier belongs to the day before.
    await _seed_user_at(db_session, "first@example.com", midnight)
    await _seed_user_at(
        db_session, "last@example.com", midnight + timedelta(days=1, microseconds=-1)
    )
    await _seed_user_at(db_session, "prev@example.com", midnight - timedelta(microseconds=1))

    resp = await client.get(SIGNUPS_URL, params={"days": 3}, headers=_auth(admin_id))

    assert resp.status_code == 200, resp.text
    assert resp.json()["buckets"] == [
        {"day": str(today - timedelta(days=2)), "count": 1},
        {"day": str(yesterday), "count": 2},
        {"day": str(today), "count": 0},
    ]
