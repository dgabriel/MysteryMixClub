"""Tests for MYS-109: round-lifecycle email notifications.

Covers the event→email mapping at each state transition, recipient filtering
(unsubscribed / removed members are skipped), the one-click unsubscribe
endpoint, and the profile preference surface. Notifications are scheduled as
FastAPI background tasks; the ASGI test transport runs them before the response
returns, so the spy sender has recorded them by the time a request resolves.

Rounds are created through the autogen flow (POST /leagues seeds N *pending*
rounds), then opened via PATCH — matching real usage. The legacy POST /rounds
path defaults a round straight to open_submission, which wouldn't exercise the
pending→open transition we notify on.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token, create_unsubscribe_token
from app.models.league import League  # noqa: F401 — kept for parity/readability
from app.models.league_member import LeagueMember
from app.models.user import User


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name, default_vibe_mode=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _create_league(client, user_id, *, total_rounds: int = 2):
    resp = await client.post(
        "/api/v1/leagues",
        json={"name": "Friday Mixtape", "total_rounds": total_rounds},
        headers=_auth(user_id),
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _add_member(db_session, league_id, user) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


async def _round_id(client, league_id, user_id, number: int) -> str:
    resp = await client.get(f"/api/v1/leagues/{league_id}/rounds", headers=_auth(user_id))
    assert resp.status_code == 200, resp.text
    for r in resp.json():
        if r["round_number"] == number:
            return r["id"]
    raise AssertionError(f"round {number} not found")


async def _advance(client, round_id, organizer_id, state):
    return await client.patch(
        f"/api/v1/rounds/{round_id}", json={"state": state}, headers=_auth(organizer_id)
    )


async def _league_with_members(client, db_session, *, n_members: int = 2, total_rounds: int = 2):
    organizer = await _seed_user(db_session, "org@example.com", "Org")
    league_id = await _create_league(client, organizer.id, total_rounds=total_rounds)
    members = []
    for i in range(n_members):
        m = await _seed_user(db_session, f"m{i}@example.com", f"M{i}")
        await _add_member(db_session, league_id, m)
        members.append(m)
    return organizer, league_id, members


# --------------------------------------------------------------------------- #
# Event → email mapping
# --------------------------------------------------------------------------- #


async def test_opening_submission_emails_all_members(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(client, db_session)
    rid = await _round_id(client, league_id, organizer.id, 1)

    email_spy.sends.clear()
    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 200

    recipients = {to for (to, _subj, _html) in email_spy.sends}
    assert recipients == {"org@example.com", "m0@example.com", "m1@example.com"}
    assert "open for submissions" in email_spy.sends[0][1]


async def test_voting_open_emails_all_members(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(client, db_session)
    rid = await _round_id(client, league_id, organizer.id, 1)
    await _advance(client, rid, organizer.id, "open_submission")

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "open_voting")

    assert len(email_spy.sends) == 3
    assert all("voting is open" in subj for (_to, subj, _html) in email_spy.sends)


async def test_closing_round_emails_and_notifies_auto_opened_next(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(client, db_session, total_rounds=2)
    rid = await _round_id(client, league_id, organizer.id, 1)
    await _advance(client, rid, organizer.id, "open_submission")
    await _advance(client, rid, organizer.id, "open_voting")

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "closed")

    subjects = [subj for (_to, subj, _html) in email_spy.sends]
    # 3 members × (round_closed for r1 + submission_open for the auto-opened r2)
    assert len(email_spy.sends) == 6
    assert sum("results are in" in s for s in subjects) == 3
    assert sum("open for submissions" in s for s in subjects) == 3


async def test_closing_final_round_emails_completion(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(
        client, db_session, n_members=1, total_rounds=1
    )
    rid = await _round_id(client, league_id, organizer.id, 1)
    await _advance(client, rid, organizer.id, "open_submission")
    await _advance(client, rid, organizer.id, "open_voting")

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "closed")

    subjects = [subj for (_to, subj, _html) in email_spy.sends]
    # 2 members (organizer + m0) × (round_closed + league_complete)
    assert sum("results are in" in s for s in subjects) == 2
    assert sum("the league is complete" in s for s in subjects) == 2


# --------------------------------------------------------------------------- #
# Recipient filtering
# --------------------------------------------------------------------------- #


async def test_unsubscribed_member_is_skipped(client, db_session, email_spy):
    organizer, league_id, members = await _league_with_members(client, db_session)
    members[0].email_notifications = False
    await db_session.commit()
    rid = await _round_id(client, league_id, organizer.id, 1)

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "open_submission")

    recipients = {to for (to, _s, _h) in email_spy.sends}
    assert recipients == {"org@example.com", "m1@example.com"}


async def test_removed_member_is_skipped(client, db_session, email_spy):
    organizer, league_id, members = await _league_with_members(client, db_session)
    lm = await db_session.scalar(select(LeagueMember).where(LeagueMember.user_id == members[0].id))
    lm.removed_at = datetime.now(timezone.utc)
    await db_session.commit()
    rid = await _round_id(client, league_id, organizer.id, 1)

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "open_submission")

    recipients = {to for (to, _s, _h) in email_spy.sends}
    assert "m0@example.com" not in recipients


# --------------------------------------------------------------------------- #
# Unsubscribe endpoint
# --------------------------------------------------------------------------- #


async def test_unsubscribe_flips_flag(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    user_id = user.id  # capture before expire_all (avoid the async lazy-load trap)
    token = create_unsubscribe_token(user_id)

    resp = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    assert resp.status_code == 200
    assert "unsubscribed" in resp.text.lower()

    db_session.expire_all()
    refreshed = await db_session.get(User, user_id)
    assert refreshed is not None
    assert refreshed.email_notifications is False


async def test_unsubscribe_invalid_token_is_calm(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    user_id = user.id

    resp = await client.get("/api/v1/notifications/unsubscribe?token=not-a-real-token")
    assert resp.status_code == 200
    assert "didn't work" in resp.text.lower()

    db_session.expire_all()
    refreshed = await db_session.get(User, user_id)
    assert refreshed is not None
    assert refreshed.email_notifications is True  # unchanged


async def test_unsubscribe_link_present_in_email(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(client, db_session, n_members=1)
    rid = await _round_id(client, league_id, organizer.id, 1)

    email_spy.sends.clear()
    await _advance(client, rid, organizer.id, "open_submission")

    _to, _subj, html = email_spy.sends[0]
    assert "/api/v1/notifications/unsubscribe?token=" in html


async def test_unsubscribe_header_present(client, db_session, email_spy):
    organizer, league_id, _members = await _league_with_members(client, db_session, n_members=1)
    rid = await _round_id(client, league_id, organizer.id, 1)

    email_spy.sends.clear()
    email_spy.sent_headers.clear()
    await _advance(client, rid, organizer.id, "open_submission")

    headers = email_spy.sent_headers[0]
    assert headers is not None
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/api/v1/notifications/unsubscribe?token=" in headers["List-Unsubscribe"]


# --------------------------------------------------------------------------- #
# Profile preference surface
# --------------------------------------------------------------------------- #


async def test_profile_exposes_and_updates_preference(client, db_session):
    user = await _seed_user(db_session, "u@example.com")
    me = await client.get("/api/v1/users/me", headers=_auth(user.id))
    assert me.json()["email_notifications"] is True

    patched = await client.patch(
        "/api/v1/users/me", json={"email_notifications": False}, headers=_auth(user.id)
    )
    assert patched.status_code == 200
    assert patched.json()["email_notifications"] is False
