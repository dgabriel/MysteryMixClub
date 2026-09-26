"""Tests for MysteryMixClub-4vii.48.1: member content reports on /admin.

The platform-admin operator view over the reports table (4vii.48's operator
visibility piece):

    GET  /admin/reports?status=open|reviewed|all&limit=&offset=  -> {items, total}
    POST /admin/reports/{id}/review                              -> updated row

Covers authorization (401 unauthenticated, 403 authenticated non-admin),
default-open filtering plus the reviewed/all views, newest-first ordering,
limit/offset pagination against a real total, per-row context (club name,
both parties, the reported note with its song + mix label), the resilience
cases the acceptance criteria call out (purged reporter/reported-user ->
null; vanished note -> null content), and mark-reviewed persistence +
idempotency + 404.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.report import Report
from app.models.submission import Submission
from app.models.user import User

ADMIN_EMAIL = "admin@example.com"
REPORTS_URL = "/api/v1/admin/reports"


def _review_url(report_id) -> str:
    return f"/api/v1/admin/reports/{report_id}/review"


@pytest.fixture
def seed_admin_emails() -> str:
    return ADMIN_EMAIL


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_admin(db_session) -> User:
    return await _seed_user(db_session, ADMIN_EMAIL, "Admin")


async def _seed_club_with_mix(db_session, organizer: User) -> tuple[Club, Mix]:
    club = Club(name="Review Club", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    mix_ = Mix(club_id=club.id, mix_number=2, theme="slow burns", state="closed")
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(club)
    await db_session.refresh(mix_)
    return club, mix_


async def _seed_report(
    db_session,
    *,
    club: Club,
    reporter: User | None,
    reported: User | None,
    reason: str = "harassment",
    detail: str | None = None,
    status: str = "open",
    note: Note | None = None,
    created_at=None,
) -> Report:
    content_id = note.id if note else uuid.uuid4()
    report = Report(
        reporter_id=reporter.id if reporter else None,
        reported_user_id=reported.id if reported else None,
        club_id=club.id,
        content_type="note",
        content_id=content_id,
        reason=reason,
        detail=detail,
        status=status,
    )
    if created_at is not None:
        # Tests bind one savepoint-wrapped connection (ADR 0005), so
        # server_default func.now() is transactional — every row in a test gets
        # the same created_at. Order-sensitive tests pass explicit times.
        report.created_at = created_at
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    return report


async def _seed_note(db_session, mix_: Mix, author: User, *, body: str) -> Note:
    sub = Submission(
        mix_id=mix_.id,
        user_id=author.id,
        isrc="USABC1234567",
        title="Debaser",
        artist="Pixies",
    )
    db_session.add(sub)
    await db_session.flush()
    note = Note(mix_id=mix_.id, author_id=author.id, submission_id=sub.id, body=body)
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)
    return note


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #


async def test_reports_list_requires_auth(client):
    resp = await client.get(REPORTS_URL)
    assert resp.status_code == 401, resp.text


async def test_reports_list_rejects_non_admin(client, db_session):
    user = await _seed_user(db_session, "m@example.com", "Mia")
    resp = await client.get(REPORTS_URL, headers=_auth_header(user.id))
    assert resp.status_code == 403, resp.text


async def test_review_requires_auth_and_admin(client, db_session):
    user = await _seed_user(db_session, "n@example.com", "Ned")
    report_id = uuid.uuid4()

    assert (await client.post(_review_url(report_id))).status_code == 401
    assert (
        await client.post(_review_url(report_id), headers=_auth_header(user.id))
    ).status_code == 403


# --------------------------------------------------------------------------- #
# Filtering, ordering, pagination
# --------------------------------------------------------------------------- #


async def test_lists_open_by_default_with_full_context(client, db_session):
    admin = await _seed_admin(db_session)
    reporter = await _seed_user(db_session, "r@example.com", "Ria")
    reported = await _seed_user(db_session, "t@example.com", "Ted")
    club, mix_ = await _seed_club_with_mix(db_session, reported)
    note = await _seed_note(db_session, mix_, reported, body="you all have no taste")
    report = await _seed_report(
        db_session,
        club=club,
        reporter=reporter,
        reported=reported,
        detail="third time this week",
        note=note,
    )
    # A reviewed report must not show in the default open view.
    await _seed_report(
        db_session,
        club=club,
        reporter=reporter,
        reported=reported,
        status="reviewed",
        note=note,
    )

    resp = await client.get(REPORTS_URL, headers=_auth_header(admin.id))

    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total"] == 1
    (row,) = page["items"]
    assert row["id"] == str(report.id)
    assert row["reason"] == "harassment"
    assert row["detail"] == "third time this week"
    assert row["status"] == "open"
    assert row["club_name"] == "Review Club"
    assert row["reporter"] == {
        "user_id": str(reporter.id),
        "display_name": "Ria",
        "email": "r@example.com",
    }
    assert row["reported_user"]["display_name"] == "Ted"
    assert row["reported_user"]["email"] == "t@example.com"
    assert row["content"] == {
        "kind": "note",
        "content_id": str(note.id),
        "body": "you all have no taste",
        "song_title": "Debaser",
        "song_artist": "Pixies",
        "mix_label": "mix 2 · slow burns",
    }


async def test_status_filter_and_newest_first(client, db_session):
    admin = await _seed_admin(db_session)
    reporter = await _seed_user(db_session, "o@example.com", "Ola")
    reported = await _seed_user(db_session, "p@example.com", "Pat")
    club, _mix = await _seed_club_with_mix(db_session, reported)
    t0 = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    first = await _seed_report(
        db_session, club=club, reporter=reporter, reported=reported, created_at=t0
    )
    await _seed_report(
        db_session,
        club=club,
        reporter=reporter,
        reported=reported,
        status="reviewed",
        created_at=t0 + timedelta(minutes=5),
    )
    third = await _seed_report(
        db_session,
        club=club,
        reporter=reporter,
        reported=reported,
        created_at=t0 + timedelta(minutes=10),
    )

    open_page = (
        await client.get(f"{REPORTS_URL}?status=open", headers=_auth_header(admin.id))
    ).json()
    assert [r["id"] for r in open_page["items"]] == [str(third.id), str(first.id)]

    reviewed_page = (
        await client.get(f"{REPORTS_URL}?status=reviewed", headers=_auth_header(admin.id))
    ).json()
    assert reviewed_page["total"] == 1
    assert reviewed_page["items"][0]["status"] == "reviewed"

    all_page = (
        await client.get(f"{REPORTS_URL}?status=all", headers=_auth_header(admin.id))
    ).json()
    assert all_page["total"] == 3


async def test_paginates_with_limit_and_offset(client, db_session):
    admin = await _seed_admin(db_session)
    reporter = await _seed_user(db_session, "q@example.com", "Quinn")
    reported = await _seed_user(db_session, "s@example.com", "Sam")
    club, _mix = await _seed_club_with_mix(db_session, reported)
    for _ in range(3):
        await _seed_report(db_session, club=club, reporter=reporter, reported=reported)

    page1 = (
        await client.get(f"{REPORTS_URL}?limit=2&offset=0", headers=_auth_header(admin.id))
    ).json()
    page2 = (
        await client.get(f"{REPORTS_URL}?limit=2&offset=2", headers=_auth_header(admin.id))
    ).json()

    assert page1["total"] == 3
    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 1
    assert page1["items"][0]["id"] != page2["items"][0]["id"]

    bad = await client.get(f"{REPORTS_URL}?limit=0", headers=_auth_header(admin.id))
    assert bad.status_code == 422


# --------------------------------------------------------------------------- #
# Resilience: purged users, vanished content
# --------------------------------------------------------------------------- #


async def test_purged_parties_and_missing_note_render_as_nulls(client, db_session):
    """After account purge the report keeps meaning (4vii.38's SET NULL), and a
    note row that no longer exists must not take the whole row down."""
    admin = await _seed_admin(db_session)
    reporter = await _seed_user(db_session, "u@example.com", "Uma")
    club, _mix = await _seed_club_with_mix(db_session, reporter)
    report = await _seed_report(
        db_session,
        club=club,
        reporter=None,  # reporter purged
        reported=None,  # reported user purged
        note=None,  # content_id points at nothing
        reason="other",
    )

    row = (await client.get(REPORTS_URL, headers=_auth_header(admin.id))).json()["items"][0]
    assert row["id"] == str(report.id)
    assert row["reporter"] is None
    assert row["reported_user"] is None
    assert row["content"] is None
    assert row["club_name"] == "Review Club"


# --------------------------------------------------------------------------- #
# Mark reviewed
# --------------------------------------------------------------------------- #


async def test_mark_reviewed_persists_and_drops_off_the_open_queue(client, db_session):
    admin = await _seed_admin(db_session)
    reporter = await _seed_user(db_session, "v@example.com", "Val")
    reported = await _seed_user(db_session, "w@example.com", "Wes")
    club, _mix = await _seed_club_with_mix(db_session, reported)
    report = await _seed_report(db_session, club=club, reporter=reporter, reported=reported)

    resp = await client.post(_review_url(report.id), headers=_auth_header(admin.id))

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "reviewed"
    await db_session.refresh(report)
    assert report.status == "reviewed"

    open_page = (await client.get(REPORTS_URL, headers=_auth_header(admin.id))).json()
    assert open_page["total"] == 0
    reviewed_page = (
        await client.get(f"{REPORTS_URL}?status=reviewed", headers=_auth_header(admin.id))
    ).json()
    assert reviewed_page["total"] == 1

    # Idempotent: reviewing again returns the row, not an error.
    again = await client.post(_review_url(report.id), headers=_auth_header(admin.id))
    assert again.status_code == 200


async def test_review_unknown_report_404s(client, db_session):
    admin = await _seed_admin(db_session)
    resp = await client.post(_review_url(uuid.uuid4()), headers=_auth_header(admin.id))
    assert resp.status_code == 404, resp.text
