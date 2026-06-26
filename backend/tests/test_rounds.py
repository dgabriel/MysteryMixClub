"""Tests for MYS-18: round creation, read, and the state machine.

Covers auth/membership/organizer gates, sequential round numbering and the
"close the current round first" rule, the forward-only state machine
(open_submission -> open_voting -> closed) including invalid transitions, and
league completion when the final round closes. Playlist generation is a
separate slice (depends on submissions, MYS-51) and is not exercised here.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.submission import Submission
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


async def _seed_league(
    db_session, organizer: User, *, total_rounds: int = 3, votes_per_player: int = 3
) -> League:
    league = League(
        name="Friday Mixtape",
        organizer_id=organizer.id,
        total_rounds=total_rounds,
        votes_per_player=votes_per_player,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(league)
    return league


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _rounds_url(league_id: uuid.UUID) -> str:
    return f"/api/v1/leagues/{league_id}/rounds"


async def _create_round(client, league_id, organizer_id, **body):
    body.setdefault("theme", "late summer feels")
    return await client.post(_rounds_url(league_id), json=body, headers=_auth(organizer_id))


async def _advance(client, round_id, organizer_id, state):
    return await client.patch(
        f"/api/v1/rounds/{round_id}", json={"state": state}, headers=_auth(organizer_id)
    )


# --------------------------------------------------------------------------- #
# Create — auth / authorization
# --------------------------------------------------------------------------- #


async def test_create_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.post(_rounds_url(league.id), json={"theme": "x"})
    assert resp.status_code == 401


async def test_create_non_organizer_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)

    resp = await client.post(_rounds_url(league.id), json={"theme": "x"}, headers=_auth(member.id))
    assert resp.status_code == 403


async def test_create_missing_theme_is_allowed(client, db_session):
    # theme is now optional (MYS-62): a round may be created without one.
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.post(_rounds_url(league.id), json={}, headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["theme"] is None


# --------------------------------------------------------------------------- #
# Create — happy paths + sequencing
# --------------------------------------------------------------------------- #


async def test_create_first_round_defaults(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, votes_per_player=5)
    league_id = league.id

    resp = await _create_round(client, league_id, organizer.id, theme="  golden hour  ")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["round_number"] == 1
    assert body["state"] == "open_submission"
    assert body["theme"] == "golden hour"  # trimmed
    assert body["votes_per_player"] == 5  # inherited from the league
    assert body["closed_at"] is None

    # The new round becomes the league's active round.
    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.current_round == 1


async def test_create_round_votes_override(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, votes_per_player=3)
    resp = await _create_round(client, league.id, organizer.id, votes_per_player=1)
    assert resp.status_code == 201
    assert resp.json()["votes_per_player"] == 1


async def test_cannot_create_second_round_while_first_open(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    first = await _create_round(client, league.id, organizer.id)
    assert first.status_code == 201

    second = await _create_round(client, league.id, organizer.id)
    assert second.status_code == 409
    assert "closed" in second.json()["detail"]


async def test_sequential_numbering_after_closing(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=3)

    r1 = await _create_round(client, league.id, organizer.id)
    rid1 = r1.json()["id"]
    assert (await _advance(client, rid1, organizer.id, "open_voting")).status_code == 200
    assert (await _advance(client, rid1, organizer.id, "closed")).status_code == 200

    r2 = await _create_round(client, league.id, organizer.id)
    assert r2.status_code == 201
    assert r2.json()["round_number"] == 2


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


async def test_list_rounds_ordered_for_member(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)
    await _create_round(client, league.id, organizer.id, theme="one")

    resp = await client.get(_rounds_url(league.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    rounds = resp.json()
    assert [r["round_number"] for r in rounds] == [1]


async def test_list_rounds_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    outsider = await _seed_user(db_session, "outsider@example.com")
    league = await _seed_league(db_session, organizer)
    resp = await client.get(_rounds_url(league.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_get_round_detail(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    created = await _create_round(client, league.id, organizer.id, theme="the one that got away")
    rid = created.json()["id"]

    resp = await client.get(f"/api/v1/rounds/{rid}", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == "the one that got away"


async def test_get_unknown_round_404(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    await _seed_league(db_session, organizer)
    resp = await client.get(f"/api/v1/rounds/{uuid.uuid4()}", headers=_auth(organizer.id))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #


async def test_full_forward_transitions(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=2)  # not the final round
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]

    to_voting = await _advance(client, rid, organizer.id, "open_voting")
    assert to_voting.status_code == 200
    assert to_voting.json()["state"] == "open_voting"

    to_closed = await _advance(client, rid, organizer.id, "closed")
    assert to_closed.status_code == 200
    assert to_closed.json()["state"] == "closed"
    assert to_closed.json()["closed_at"] is not None


async def test_skipping_a_state_is_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]

    resp = await _advance(client, rid, organizer.id, "closed")  # skips open_voting
    assert resp.status_code == 409


async def test_backwards_transition_is_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 409


async def test_editing_closed_round_is_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=2)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await client.patch(
        f"/api/v1/rounds/{rid}", json={"theme": "too late"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 409


async def test_patch_requires_organizer(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]

    resp = await client.patch(
        f"/api/v1/rounds/{rid}", json={"state": "open_voting"}, headers=_auth(member.id)
    )
    assert resp.status_code == 403


async def test_patch_updates_deadline_on_open_round(client, db_session):
    # A round created via single-create is born open_submission. Deadlines stay
    # editable until the round closes, so a deadline-only edit still succeeds.
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]

    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    resp = await client.patch(
        f"/api/v1/rounds/{rid}",
        json={"submission_deadline": deadline},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_deadline"] is not None


async def test_patch_theme_on_open_round_is_rejected(client, db_session):
    # theme is locked once a round opens (MYS-62 edit lock). A single-created
    # round is born open_submission, so editing its theme is a 409.
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]

    resp = await client.patch(
        f"/api/v1/rounds/{rid}",
        json={"theme": "rainy day b-sides"},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409, resp.text
    assert "locked" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# League completion
# --------------------------------------------------------------------------- #


async def test_closing_final_round_completes_league(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=1)
    league_id = league.id
    rid = (await _create_round(client, league_id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.state == "complete"
    assert league.completed_at is not None


async def test_closing_nonfinal_round_does_not_complete_league(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=2)
    league_id = league.id
    rid = (await _create_round(client, league_id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    db_session.expire_all()
    league = await db_session.scalar(select(League).where(League.id == league_id))
    assert league.state == "active"
    assert league.completed_at is None


async def test_cannot_create_round_on_complete_league(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=1)
    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await _create_round(client, league.id, organizer.id)
    assert resp.status_code == 409
    assert "complete" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Submission progress (MYS-101)
# --------------------------------------------------------------------------- #


async def _add_submission(db_session, round_id: uuid.UUID, user: User) -> None:
    db_session.add(
        Submission(
            round_id=round_id,
            user_id=user.id,
            isrc=f"ISRC-{user.id}",
            title="A song",
            artist="An artist",
            participation_mode="playing",
        )
    )
    await db_session.commit()


async def test_round_reports_submission_and_member_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    other = await _seed_user(db_session, "other@example.com")
    league = await _seed_league(db_session, organizer)
    await _add_member(db_session, league.id, member)
    await _add_member(db_session, league.id, other)

    # A fresh round on creation has no submissions yet but knows the member count.
    created = (await _create_round(client, league.id, organizer.id)).json()
    rid = created["id"]
    assert created["submission_count"] == 0
    assert created["member_count"] == 3

    await _add_submission(db_session, uuid.UUID(rid), organizer)

    detail = await client.get(f"/api/v1/rounds/{rid}", headers=_auth(member.id))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["submission_count"] == 1  # 3 members, 1 has submitted
    assert body["member_count"] == 3


async def test_list_rounds_includes_per_round_submission_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    league = await _seed_league(db_session, organizer, total_rounds=3)
    await _add_member(db_session, league.id, member)

    rid = (await _create_round(client, league.id, organizer.id)).json()["id"]
    await _add_submission(db_session, uuid.UUID(rid), organizer)
    await _add_submission(db_session, uuid.UUID(rid), member)

    resp = await client.get(_rounds_url(league.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    by_number = {r["round_number"]: r for r in resp.json()}
    assert by_number[1]["submission_count"] == 2
    assert by_number[1]["member_count"] == 2
