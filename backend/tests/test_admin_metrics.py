"""Tests for MysteryMixClub-etz7.1: GET /api/v1/admin/metrics.

Aggregate-only platform snapshot (technical-design §10 — no user-level
tracking), gated by the same get_platform_admin dependency as the rest of
/admin. Covers authorization (401 unauthenticated, 403 authenticated
non-admin), every aggregate field against known seeded data, and the
empty-platform edge case (all zeros, avg 0.0 rather than a divide-by-zero).
"""

from datetime import datetime, timezone

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
