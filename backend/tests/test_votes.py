"""Tests for MYS-20: voting endpoints.

Covers the full cast-votes validation matrix (in declared check order), the
Playing-player happy path at the max-vote boundary, idempotent replace-on-recast,
and the GET /votes/mine read (cast set, ordering, and the empty case).

Voting has no external dependency to fake, so these use the shared ``client``
fixture. Submissions are seeded directly in the DB so each test controls the
exact participation_mode and ownership it needs.
"""

import uuid

from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str) -> User:
    user = User(email=email, display_name="U")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league_with_round(
    db_session, organizer: User, *, state: str = "open_voting", votes_per_player: int = 3
) -> Round:
    league = League(
        name="L",
        organizer_id=organizer.id,
        total_rounds=3,
        votes_per_player=votes_per_player,
    )
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="late summer",
        state=state,
        votes_per_player=votes_per_player,
    )
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


async def _seed_submission(
    db_session, round_id: uuid.UUID, user: User, *, mode: str = "playing", title: str = "song"
) -> Submission:
    sub = Submission(
        round_id=round_id,
        user_id=user.id,
        isrc="USABC1234567",
        title=title,
        artist="Artist",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _votes_url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/votes"


# --------------------------------------------------------------------------- #
# POST — validation matrix (declared check order in cast_votes)
# --------------------------------------------------------------------------- #


async def test_cast_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.post(_votes_url(round_.id), json={"submission_ids": [str(uuid.uuid4())]})
    assert resp.status_code == 401


async def test_cast_round_missing_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    await _seed_league_with_round(db_session, organizer)
    resp = await client.post(
        _votes_url(uuid.uuid4()),
        json={"submission_ids": [str(uuid.uuid4())]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "round not found"


async def test_cast_non_member_403(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(uuid.uuid4())]},
        headers=_auth(outsider.id),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "you are not a member of this league"


async def test_cast_round_not_open_voting_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_submission")
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(uuid.uuid4())]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "voting is not open for this round"


async def test_cast_without_own_submission_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    voter = await _seed_user(db_session, "v@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, voter)
    # A target exists, but the voter has not submitted anything.
    target = await _seed_submission(db_session, round_.id, organizer)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(target.id)]},
        headers=_auth(voter.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "submit a song before voting"


async def test_cast_when_own_submission_is_vibing_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    voter = await _seed_user(db_session, "v@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, voter)
    target = await _seed_submission(db_session, round_.id, organizer)
    await _seed_submission(db_session, round_.id, voter, mode="vibing")
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(target.id)]},
        headers=_auth(voter.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "just vibing players don't cast votes — leave a note instead"


async def test_cast_zero_votes_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _seed_submission(db_session, round_.id, organizer)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": []},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "you may cast up to 3 votes"


async def test_cast_too_many_votes_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, votes_per_player=2)
    await _seed_submission(db_session, round_.id, organizer)
    # Four distinct ids, votes_per_player is 2.
    ids = [str(uuid.uuid4()) for _ in range(4)]
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": ids},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "you may cast up to 2 votes"


async def test_cast_duplicate_ids_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    voter = await _seed_user(db_session, "v@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, voter)
    target = await _seed_submission(db_session, round_.id, organizer)
    await _seed_submission(db_session, round_.id, voter)
    tid = str(target.id)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [tid, tid]},
        headers=_auth(voter.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "duplicate votes are not allowed"


async def test_cast_id_not_in_round_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _seed_submission(db_session, round_.id, organizer)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(uuid.uuid4())]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "submission not found in this round"


async def test_cast_id_from_another_round_404(client, db_session):
    # A real submission, but it belongs to a different round.
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _seed_submission(db_session, round_.id, organizer)
    # Second round under the same league with its own submission.
    league_id = round_.league_id
    other_round = Round(league_id=league_id, round_number=2, theme="other", state="open_voting")
    db_session.add(other_round)
    await db_session.commit()
    await db_session.refresh(other_round)
    foreign = await _seed_submission(db_session, other_round.id, organizer, title="foreign")
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(foreign.id)]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "submission not found in this round"


async def test_cast_for_own_song_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    own = await _seed_submission(db_session, round_.id, organizer)
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(own.id)]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "you can't vote for your own song"


async def test_cast_for_vibing_song_succeeds(client, db_session):
    # MYS-112: a viber's song competes like any other — it is votable, and the
    # voter can't tell it was a viber's.
    organizer = await _seed_user(db_session, "o@example.com")
    viber = await _seed_user(db_session, "vibe@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    await _add_member(db_session, round_.league_id, viber)
    await _seed_submission(db_session, round_.id, organizer)  # voter's own song
    vibing_sub = await _seed_submission(db_session, round_.id, viber, mode="vibing")
    resp = await client.post(
        _votes_url(round_.id),
        json={"submission_ids": [str(vibing_sub.id)]},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_ids"] == [str(vibing_sub.id)]


# --------------------------------------------------------------------------- #
# POST — happy paths
# --------------------------------------------------------------------------- #


async def test_cast_max_votes_happy_path(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    a = await _seed_user(db_session, "a@example.com")
    b = await _seed_user(db_session, "b@example.com")
    c = await _seed_user(db_session, "c@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, votes_per_player=3)
    round_id = round_.id
    league_id = round_.league_id
    for u in (a, b, c):
        await _add_member(db_session, league_id, u)
    await _seed_submission(db_session, round_id, organizer)  # voter's own song
    s_a = await _seed_submission(db_session, round_id, a, title="A")
    s_b = await _seed_submission(db_session, round_id, b, title="B")
    s_c = await _seed_submission(db_session, round_id, c, title="C")
    voter_id = organizer.id
    target_ids = [str(s_a.id), str(s_b.id), str(s_c.id)]

    resp = await client.post(
        _votes_url(round_id), json={"submission_ids": target_ids}, headers=_auth(voter_id)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_id"] == str(round_id)
    assert body["count"] == 3
    assert body["votes_per_player"] == 3
    assert sorted(body["submission_ids"]) == sorted(target_ids)

    db_session.expire_all()
    count = await db_session.scalar(
        select(func.count())
        .select_from(Vote)
        .where(Vote.round_id == round_id, Vote.voter_id == voter_id)
    )
    assert count == 3


async def test_recast_replaces_idempotent(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    a = await _seed_user(db_session, "a@example.com")
    b = await _seed_user(db_session, "b@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, votes_per_player=2)
    round_id = round_.id
    league_id = round_.league_id
    for u in (a, b):
        await _add_member(db_session, league_id, u)
    await _seed_submission(db_session, round_id, organizer)
    s_a = await _seed_submission(db_session, round_id, a, title="A")
    s_b = await _seed_submission(db_session, round_id, b, title="B")
    voter_id = organizer.id

    first = await client.post(
        _votes_url(round_id), json={"submission_ids": [str(s_a.id)]}, headers=_auth(voter_id)
    )
    assert first.status_code == 200, first.text
    # Re-cast with a different (and larger) set; should replace, not append.
    second = await client.post(
        _votes_url(round_id),
        json={"submission_ids": [str(s_a.id), str(s_b.id)]},
        headers=_auth(voter_id),
    )
    assert second.status_code == 200, second.text
    assert second.json()["count"] == 2

    # Capture PKs into locals before expire_all() — reading expired ORM
    # attributes later raises MissingGreenlet in async tests.
    s_a_id, s_b_id = s_a.id, s_b.id
    db_session.expire_all()
    rows = list(
        await db_session.scalars(
            select(Vote).where(Vote.round_id == round_id, Vote.voter_id == voter_id)
        )
    )
    assert len(rows) == 2  # not 3 — prior vote replaced, not doubled
    assert {str(r.submission_id) for r in rows} == {str(s_a_id), str(s_b_id)}


# --------------------------------------------------------------------------- #
# GET /votes/mine
# --------------------------------------------------------------------------- #


async def test_get_mine_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.get(f"{_votes_url(round_.id)}/mine")
    assert resp.status_code == 401


async def test_get_mine_non_member_403(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    outsider = await _seed_user(db_session, "x@example.com")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.get(f"{_votes_url(round_.id)}/mine", headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_get_mine_unknown_round_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    await _seed_league_with_round(db_session, organizer)
    resp = await client.get(f"{_votes_url(uuid.uuid4())}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 404


async def test_get_mine_returns_cast_votes_ordered(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    a = await _seed_user(db_session, "a@example.com")
    b = await _seed_user(db_session, "b@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, votes_per_player=2)
    round_id = round_.id
    league_id = round_.league_id
    for u in (a, b):
        await _add_member(db_session, league_id, u)
    await _seed_submission(db_session, round_id, organizer)
    s_a = await _seed_submission(db_session, round_id, a, title="A")
    s_b = await _seed_submission(db_session, round_id, b, title="B")
    voter_id = organizer.id
    target_ids = [str(s_a.id), str(s_b.id)]

    cast = await client.post(
        _votes_url(round_id), json={"submission_ids": target_ids}, headers=_auth(voter_id)
    )
    assert cast.status_code == 200, cast.text

    resp = await client.get(f"{_votes_url(round_id)}/mine", headers=_auth(voter_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["round_id"] == str(round_id)
    assert body["count"] == 2
    assert body["votes_per_player"] == 2
    # Ordered by created_at asc — preserves cast order.
    assert body["submission_ids"] == target_ids


async def test_get_mine_empty_when_nothing_cast(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_league_with_round(db_session, organizer, votes_per_player=4)
    resp = await client.get(f"{_votes_url(round_.id)}/mine", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission_ids"] == []
    assert body["count"] == 0
    assert body["votes_per_player"] == 4
