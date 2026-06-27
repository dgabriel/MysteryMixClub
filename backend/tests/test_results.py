"""Tests for MYS-23: round results endpoint.

``GET /api/v1/rounds/:id/results`` is the read-only reveal that surfaces, once a
round is closed: every submission with its submitter revealed and vote tally,
per-submission notes, a leaderboard of playing players, and the Most Noted
result (reusing ``compute_most_noted``).

Gates covered: 401 unauth, 404 unknown round, 403 non-member, 409 while the
round is still ``open_submission`` or ``open_voting``.

Happy-path coverage (closed round, multi-member league with submissions, votes,
and notes): full submission list ordering and vote counts, per-submission note
ordering, leaderboard membership/ordering/ranks, and Most Noted (clear winner,
empty case, and the mode-agnostic vibing-winner case).

Notes and votes are seeded directly in the DB with explicit ``created_at``
values so ordering assertions are deterministic (the POST routes gate on
``open_voting``, but results require ``closed``). PKs are captured into locals
before any ``expire_all`` to avoid MissingGreenlet.
"""

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.jwt import create_access_token
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str) -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_league_with_round(db_session, organizer: User, *, state: str = "closed") -> Round:
    league = League(name="L", organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(
        league_id=league.id,
        round_number=1,
        theme="late summer feels",
        state=state,
    )
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _add_member(db_session, league_id: uuid.UUID, user: User) -> None:
    db_session.add(LeagueMember(league_id=league_id, user_id=user.id))
    await db_session.commit()


async def _seed_submission(
    db_session,
    round_: Round,
    user: User,
    *,
    title: str = "song",
    artist: str = "Artist",
    mode: str = "playing",
    note: str | None = None,
) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title=title,
        artist=artist,
        album="An Album",
        album_art_url="https://example.com/art.jpg",
        participation_mode=mode,
        note=note,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _seed_vote(db_session, round_id, voter: User, submission: Submission) -> None:
    db_session.add(Vote(round_id=round_id, voter_id=voter.id, submission_id=submission.id))
    await db_session.commit()


async def _seed_note(
    db_session,
    round_id,
    author: User,
    submission: Submission,
    *,
    body: str = "love this",
    created_at: datetime | None = None,
) -> None:
    note = Note(
        round_id=round_id,
        author_id=author.id,
        submission_id=submission.id,
        body=body,
    )
    if created_at is not None:
        note.created_at = created_at
    db_session.add(note)
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _url(round_id) -> str:
    return f"/api/v1/rounds/{round_id}/results"


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


async def test_results_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.get(_url(round_.id))
    assert resp.status_code == 401


async def test_results_unknown_round_404(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    await _seed_league_with_round(db_session, organizer)
    resp = await client.get(_url(uuid.uuid4()), headers=_auth(organizer.id))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "round not found"


async def test_results_non_member_403(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    outsider = await _seed_user(db_session, "x@example.com", "Out")
    round_ = await _seed_league_with_round(db_session, organizer)
    resp = await client.get(_url(round_.id), headers=_auth(outsider.id))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "you are not a member of this league"


async def test_results_open_submission_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_submission")
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "results are available once the round closes"


async def test_results_open_voting_409(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    round_ = await _seed_league_with_round(db_session, organizer, state="open_voting")
    resp = await client.get(_url(round_.id), headers=_auth(organizer.id))
    assert resp.status_code == 409
    assert resp.json()["detail"] == "results are available once the round closes"


# --------------------------------------------------------------------------- #
# Happy path 1 — full submissions: every submission, submitter revealed,
# vote counts (incl. a zero-vote submission), ordered votes desc then title asc.
# --------------------------------------------------------------------------- #


async def test_results_full_submissions_revealed_and_ordered(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    carol = await _seed_user(db_session, "c@example.com", "Carol")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    league_id = round_.league_id
    for u in (alice, bob, carol):
        await _add_member(db_session, league_id, u)

    # Alice: 2 votes; Bob: 1 vote; Carol: 0 votes.
    s_alice = await _seed_submission(db_session, round_, alice, title="Banana")
    s_bob = await _seed_submission(db_session, round_, bob, title="Apple")
    s_carol = await _seed_submission(db_session, round_, carol, title="Cherry")

    await _seed_vote(db_session, round_id, bob, s_alice)
    await _seed_vote(db_session, round_id, carol, s_alice)
    await _seed_vote(db_session, round_id, alice, s_bob)

    s_alice_id, s_bob_id, s_carol_id = s_alice.id, s_bob.id, s_carol.id
    alice_id, bob_id, carol_id = alice.id, bob.id, carol.id

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["round_id"] == str(round_id)
    assert body["round_number"] == 1
    assert body["theme"] == "late summer feels"
    assert body["state"] == "closed"

    subs = body["submissions"]
    # All three submissions present, including the zero-vote one.
    assert len(subs) == 3
    by_id = {s["submission_id"]: s for s in subs}

    assert by_id[str(s_alice_id)]["submitter_display_name"] == "Alice"
    assert by_id[str(s_alice_id)]["user_id"] == str(alice_id)
    assert by_id[str(s_alice_id)]["vote_count"] == 2
    assert by_id[str(s_bob_id)]["submitter_display_name"] == "Bob"
    assert by_id[str(s_bob_id)]["user_id"] == str(bob_id)
    assert by_id[str(s_bob_id)]["vote_count"] == 1
    # Zero-vote submission kept, vote_count defaults to 0.
    assert by_id[str(s_carol_id)]["submitter_display_name"] == "Carol"
    assert by_id[str(s_carol_id)]["user_id"] == str(carol_id)
    assert by_id[str(s_carol_id)]["vote_count"] == 0

    # Ordering: vote_count desc (Alice 2, Bob 1, Carol 0).
    assert [s["submission_id"] for s in subs] == [
        str(s_alice_id),
        str(s_bob_id),
        str(s_carol_id),
    ]


async def test_results_submissions_tiebreak_title_asc(client, db_session):
    # Two submissions tied on votes -> ordered by title A->Z.
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, bob):
        await _add_member(db_session, round_.league_id, u)

    s_alice = await _seed_submission(db_session, round_, alice, title="Zebra")
    s_bob = await _seed_submission(db_session, round_, bob, title="Antelope")
    # Each gets exactly one vote (tie on count).
    await _seed_vote(db_session, round_id, bob, s_alice)
    await _seed_vote(db_session, round_id, alice, s_bob)

    s_alice_id, s_bob_id = s_alice.id, s_bob.id

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    subs = resp.json()["submissions"]
    # Tie on vote_count (1 each) -> title asc: "Antelope" (Bob) before "Zebra" (Alice).
    assert [s["submission_id"] for s in subs] == [str(s_bob_id), str(s_alice_id)]


# --------------------------------------------------------------------------- #
# Happy path 2 — per-submission notes present, author resolved, created_at asc.
# --------------------------------------------------------------------------- #


async def test_results_per_submission_notes_ordered_and_authored(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, bob):
        await _add_member(db_session, round_.league_id, u)

    s_alice = await _seed_submission(db_session, round_, alice, title="Song A")
    s_alice_id = s_alice.id

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Insert out of chronological order; results must return them created_at asc.
    await _seed_note(
        db_session, round_id, bob, s_alice, body="second", created_at=base + timedelta(minutes=10)
    )
    await _seed_note(db_session, round_id, organizer, s_alice, body="first", created_at=base)
    await _seed_note(
        db_session, round_id, alice, s_alice, body="third", created_at=base + timedelta(minutes=20)
    )

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    subs = {s["submission_id"]: s for s in resp.json()["submissions"]}
    notes = subs[str(s_alice_id)]["notes"]

    assert [n["body"] for n in notes] == ["first", "second", "third"]
    assert [n["author_display_name"] for n in notes] == ["Org", "Bob", "Alice"]


# --------------------------------------------------------------------------- #
# Happy path 3 — leaderboard: every submitter competes (MYS-112), ordered votes
# desc then display_name asc, sequential 1-based ranks, zero-vote player last,
# vibing submitter included.
# --------------------------------------------------------------------------- #


async def test_results_leaderboard_ranks_all_submitters_including_vibers(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    carol = await _seed_user(db_session, "c@example.com", "Carol")
    viber = await _seed_user(db_session, "v@example.com", "Vera")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, bob, carol, viber):
        await _add_member(db_session, round_.league_id, u)

    s_alice = await _seed_submission(db_session, round_, alice, title="A-song")
    s_bob = await _seed_submission(db_session, round_, bob, title="B-song")
    await _seed_submission(db_session, round_, carol, title="C-song")
    s_viber = await _seed_submission(db_session, round_, viber, title="V-song", mode="vibing")

    # Alice: 2 votes, Bob: 2 votes (tie -> display_name asc: Alice then Bob),
    # Vera (vibing): 1 vote — she competes now. Carol: 0 votes (last).
    await _seed_vote(db_session, round_id, bob, s_alice)
    await _seed_vote(db_session, round_id, carol, s_alice)
    await _seed_vote(db_session, round_id, alice, s_bob)
    await _seed_vote(db_session, round_id, carol, s_bob)
    await _seed_vote(db_session, round_id, alice, s_viber)

    alice_id, bob_id, carol_id, viber_id = alice.id, bob.id, carol.id, viber.id

    # Viewer is the organizer (a non-submitter → player → full reveal).
    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    lb = body["leaderboard"]

    # Every submitter is ranked, including vibing Vera.
    lb_user_ids = [e["user_id"] for e in lb]
    assert set(lb_user_ids) == {str(alice_id), str(bob_id), str(carol_id), str(viber_id)}

    # Order: votes desc then display_name asc. Alice(2) before Bob(2) on name,
    # Vera(1), Carol(0) last. Ranks are sequential 1-based ordinals.
    assert [(e["user_id"], e["vote_count"], e["rank"]) for e in lb] == [
        (str(alice_id), 2, 1),
        (str(bob_id), 2, 2),
        (str(viber_id), 1, 3),
        (str(carol_id), 0, 4),
    ]


async def test_results_leaderboard_sums_votes_per_player_across_songs(client, db_session):
    # MYS-116: a player with multiple songs is one leaderboard standing whose
    # total sums their songs' votes; the submissions list keeps per-song counts.
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, bob):
        await _add_member(db_session, round_.league_id, u)

    # Alice submits two songs, Bob one.
    a1 = await _seed_submission(db_session, round_, alice, title="A-one")
    a2 = await _seed_submission(db_session, round_, alice, title="A-two")
    b1 = await _seed_submission(db_session, round_, bob, title="B-one")
    # Alice: a1=1 + a2=2 = 3 total; Bob: b1=2.
    await _seed_vote(db_session, round_id, bob, a1)
    await _seed_vote(db_session, round_id, organizer, a2)
    await _seed_vote(db_session, round_id, bob, a2)
    await _seed_vote(db_session, round_id, alice, b1)
    await _seed_vote(db_session, round_id, organizer, b1)

    alice_id, bob_id = alice.id, bob.id
    a1_id, a2_id, b1_id = a1.id, a2.id, b1.id

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # One row per player; Alice (3) ahead of Bob (2).
    lb = body["leaderboard"]
    assert [(e["user_id"], e["vote_count"], e["rank"]) for e in lb] == [
        (str(alice_id), 3, 1),
        (str(bob_id), 2, 2),
    ]
    # Per-song vote counts are preserved in the submissions list.
    by_id = {s["submission_id"]: s for s in body["submissions"]}
    assert by_id[str(a1_id)]["vote_count"] == 1
    assert by_id[str(a2_id)]["vote_count"] == 2
    assert by_id[str(b1_id)]["vote_count"] == 2


# --------------------------------------------------------------------------- #
# Happy path 4 — Most Noted: clear winner with notes + count; and empty case.
# --------------------------------------------------------------------------- #


async def test_results_most_noted_clear_winner(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    bob = await _seed_user(db_session, "b@example.com", "Bob")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, bob):
        await _add_member(db_session, round_.league_id, u)

    s_alice = await _seed_submission(db_session, round_, alice, title="Winner", artist="A")
    s_bob = await _seed_submission(db_session, round_, bob, title="Runner", artist="B")
    s_alice_id = s_alice.id

    base = datetime(2026, 2, 1, 9, 0, 0, tzinfo=timezone.utc)
    # Alice gets 2 notes, Bob gets 1 -> Alice is the clear Most Noted.
    await _seed_note(db_session, round_id, bob, s_alice, body="n1", created_at=base)
    await _seed_note(
        db_session, round_id, organizer, s_alice, body="n2", created_at=base + timedelta(minutes=5)
    )
    await _seed_note(db_session, round_id, alice, s_bob, body="n3", created_at=base)

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    mn = resp.json()["most_noted"]

    assert mn["note_count"] == 2
    assert len(mn["winners"]) == 1
    winner = mn["winners"][0]
    assert winner["submission_id"] == str(s_alice_id)
    assert winner["title"] == "Winner"
    assert winner["artist"] == "A"
    assert winner["note_count"] == 2
    assert [n["body"] for n in winner["notes"]] == ["n1", "n2"]
    assert [n["author_display_name"] for n in winner["notes"]] == ["Bob", "Org"]


async def test_results_most_noted_empty_when_no_notes(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    await _add_member(db_session, round_.league_id, alice)
    await _seed_submission(db_session, round_, alice, title="Lonely")

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    mn = resp.json()["most_noted"]
    assert mn["winners"] == []
    assert mn["note_count"] == 0


# --------------------------------------------------------------------------- #
# Happy path 5 — a vibing submission with the most notes is the Most Noted
# winner (mode-agnostic), and now also competes on the leaderboard (MYS-112).
# --------------------------------------------------------------------------- #


async def test_results_vibing_submission_can_be_most_noted_and_on_leaderboard(client, db_session):
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    viber = await _seed_user(db_session, "v@example.com", "Vera")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, viber):
        await _add_member(db_session, round_.league_id, u)

    s_alice = await _seed_submission(db_session, round_, alice, title="Played", mode="playing")
    s_viber = await _seed_submission(db_session, round_, viber, title="Vibed", mode="vibing")
    s_viber_id, viber_id = s_viber.id, viber.id

    base = datetime(2026, 3, 1, 8, 0, 0, tzinfo=timezone.utc)
    # Vibing submission gets the most notes (2 vs 1).
    await _seed_note(db_session, round_id, alice, s_viber, body="v1", created_at=base)
    await _seed_note(
        db_session, round_id, organizer, s_viber, body="v2", created_at=base + timedelta(minutes=2)
    )
    await _seed_note(db_session, round_id, viber, s_alice, body="a1", created_at=base)

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    mn = body["most_noted"]
    assert mn["note_count"] == 2
    assert [w["submission_id"] for w in mn["winners"]] == [str(s_viber_id)]
    assert [n["body"] for n in mn["winners"][0]["notes"]] == ["v1", "v2"]

    # The vibing submitter now competes — on the leaderboard and in submissions
    # (the viewer here is the organizer, a non-submitter, so sees the full reveal).
    assert str(viber_id) in {e["user_id"] for e in body["leaderboard"]}
    assert str(viber_id) in {s["user_id"] for s in body["submissions"]}


# --------------------------------------------------------------------------- #
# Reveal gating by viewer mode (MYS-112)
# --------------------------------------------------------------------------- #


async def test_results_vibing_viewer_gets_trimmed_reveal(client, db_session):
    """A vibing viewer sees winner(s) + Most Noted + the full tracklist (with
    notes) — but no leaderboard and no vote counts anywhere (MYS-134)."""
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    viber = await _seed_user(db_session, "v@example.com", "Vera")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    for u in (alice, viber):
        await _add_member(db_session, round_.league_id, u)

    await _seed_submission(db_session, round_, organizer, title="Org-song")
    s_alice = await _seed_submission(db_session, round_, alice, title="Winner")
    s_viber = await _seed_submission(db_session, round_, viber, title="Vibed", mode="vibing")
    s_alice_id, s_viber_id = s_alice.id, s_viber.id

    # Alice wins the vote; a note is left on the viber's own song.
    await _seed_vote(db_session, round_id, organizer, s_alice)
    await _seed_vote(db_session, round_id, viber, s_alice)
    await _seed_note(db_session, round_id, alice, s_viber, body="love this")

    resp = await client.get(_url(round_id), headers=_auth(viber.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["viewer_is_vibing"] is True
    # No rankings / scored picks leak to a viber.
    assert body["leaderboard"] == []
    assert body["submissions"] == []
    # Winner is named, but carries no vote count.
    assert [w["submission_id"] for w in body["winners"]] == [str(s_alice_id)]
    assert "vote_count" not in body["winners"][0]
    # The full tracklist is visible (title-ordered), with notes and NO vote counts.
    picks = body["picks"]
    assert [p["title"] for p in picks] == ["Org-song", "Vibed", "Winner"]
    assert all("vote_count" not in p for p in picks)
    # Tiles are playable: each pick carries its platform links (MYS-134 fix).
    assert all("platforms" in p for p in picks)
    own = next(p for p in picks if p["submission_id"] == str(s_viber_id))
    assert [n["body"] for n in own["notes"]] == ["love this"]
    # Most Noted is still present.
    assert "most_noted" in body


async def test_results_playing_viewer_gets_full_reveal(client, db_session):
    """A playing submitter sees the full reveal; the viber-only fields are empty."""
    organizer = await _seed_user(db_session, "o@example.com", "Org")
    alice = await _seed_user(db_session, "a@example.com", "Alice")
    round_ = await _seed_league_with_round(db_session, organizer)
    round_id = round_.id
    await _add_member(db_session, round_.league_id, alice)

    s_org = await _seed_submission(db_session, round_, organizer, title="Org-song", mode="playing")
    await _seed_submission(db_session, round_, alice, title="A-song")
    await _seed_vote(db_session, round_id, alice, s_org)

    resp = await client.get(_url(round_id), headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["viewer_is_vibing"] is False
    assert body["winners"] == []
    assert body["picks"] == []
    assert {s["title"] for s in body["submissions"]} == {"Org-song", "A-song"}
    assert all("platforms" in s for s in body["submissions"])
    assert len(body["leaderboard"]) == 2
