"""Tests for MYS-21: the Most Noted service (``compute_most_noted``).

Called directly with the async db session (no endpoint exists). Covers a single
clear winner (count + notes), an exact tie returning ALL winners, the empty
round (count 0 / no winners), participation-mode-agnostic eligibility, and that
non-winning submissions / their counts are excluded.

Gotcha guarded: ORM primary keys are captured into locals BEFORE the service is
invoked, since the service runs queries on the same session.
"""

from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.submission import Submission
from app.models.user import User
from app.services.most_noted import (
    MostNoted,
    MostNotedNote,
    MostNotedSubmission,
    compute_most_noted,
)


# --------------------------------------------------------------------------- #
# Seeding helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_round(db_session, organizer: User, *, state: str = "open_voting") -> Round:
    league = League(name="L", organizer_id=organizer.id, total_rounds=3, votes_per_player=3)
    db_session.add(league)
    await db_session.flush()
    db_session.add(LeagueMember(league_id=league.id, user_id=organizer.id))
    round_ = Round(league_id=league.id, round_number=1, theme="t", state=state)
    db_session.add(round_)
    await db_session.commit()
    await db_session.refresh(round_)
    return round_


async def _seed_submission(
    db_session,
    round_: Round,
    user: User,
    *,
    title: str,
    artist: str = "Artist",
    mode: str = "playing",
) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title=title,
        artist=artist,
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _add_note(db_session, round_id, submission_id, author_id, body: str) -> None:
    db_session.add(
        Note(round_id=round_id, submission_id=submission_id, author_id=author_id, body=body)
    )
    await db_session.commit()


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


async def test_empty_round_has_no_winners(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    round_ = await _seed_round(db_session, organizer)
    await _seed_submission(db_session, round_, organizer, title="lonely")
    round_id = round_.id

    result = await compute_most_noted(round_id, db_session)
    assert isinstance(result, MostNoted)
    assert result.round_id == round_id
    assert result.note_count == 0
    assert result.winners == []


async def test_single_clear_winner(db_session):
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    member = await _seed_user(db_session, "m@example.com", name="Mara")
    round_ = await _seed_round(db_session, organizer)
    sub_win = await _seed_submission(db_session, round_, organizer, title="Winner", artist="W")
    sub_lose = await _seed_submission(db_session, round_, member, title="Loser", artist="L")
    round_id, win_id, lose_id = round_.id, sub_win.id, sub_lose.id

    await _add_note(db_session, round_id, win_id, organizer.id, "incredible")
    await _add_note(db_session, round_id, win_id, member.id, "agreed")
    await _add_note(db_session, round_id, lose_id, organizer.id, "meh")

    result = await compute_most_noted(round_id, db_session)
    assert result.note_count == 2
    assert len(result.winners) == 1
    winner = result.winners[0]
    assert isinstance(winner, MostNotedSubmission)
    assert winner.submission_id == win_id
    assert winner.title == "Winner"
    assert winner.artist == "W"
    assert winner.note_count == 2
    assert {n.body for n in winner.notes} == {"incredible", "agreed"}
    assert all(isinstance(n, MostNotedNote) for n in winner.notes)
    # Non-winning submission is not present.
    assert all(w.submission_id != lose_id for w in result.winners)


async def test_winner_notes_have_author_display_name_and_order(db_session):
    organizer = await _seed_user(db_session, "o@example.com", name="Org")
    member = await _seed_user(db_session, "m@example.com", name="Mara")
    round_ = await _seed_round(db_session, organizer)
    sub = await _seed_submission(db_session, round_, organizer, title="Winner")
    round_id, sub_id = round_.id, sub.id

    await _add_note(db_session, round_id, sub_id, organizer.id, "first")
    await _add_note(db_session, round_id, sub_id, member.id, "second")

    result = await compute_most_noted(round_id, db_session)
    winner = result.winners[0]
    assert [n.body for n in winner.notes] == ["first", "second"]
    assert [n.author_display_name for n in winner.notes] == ["Org", "Mara"]


async def test_tie_returns_all_winners(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_round(db_session, organizer)
    sub_a = await _seed_submission(db_session, round_, organizer, title="A")
    sub_b = await _seed_submission(db_session, round_, member, title="B")
    round_id, a_id, b_id = round_.id, sub_a.id, sub_b.id

    await _add_note(db_session, round_id, a_id, organizer.id, "a1")
    await _add_note(db_session, round_id, b_id, member.id, "b1")

    result = await compute_most_noted(round_id, db_session)
    assert result.note_count == 1
    assert len(result.winners) == 2
    assert {w.submission_id for w in result.winners} == {a_id, b_id}
    assert all(w.note_count == 1 for w in result.winners)


async def test_tie_excludes_lower_count_submission(db_session):
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    third = await _seed_user(db_session, "t@example.com")
    round_ = await _seed_round(db_session, organizer)
    sub_a = await _seed_submission(db_session, round_, organizer, title="A")
    sub_b = await _seed_submission(db_session, round_, member, title="B")
    sub_c = await _seed_submission(db_session, round_, third, title="C")
    round_id, a_id, b_id, c_id = round_.id, sub_a.id, sub_b.id, sub_c.id

    # A and B tie at 2; C has only 1.
    await _add_note(db_session, round_id, a_id, organizer.id, "a1")
    await _add_note(db_session, round_id, a_id, member.id, "a2")
    await _add_note(db_session, round_id, b_id, organizer.id, "b1")
    await _add_note(db_session, round_id, b_id, member.id, "b2")
    await _add_note(db_session, round_id, c_id, organizer.id, "c1")

    result = await compute_most_noted(round_id, db_session)
    assert result.note_count == 2
    assert {w.submission_id for w in result.winners} == {a_id, b_id}
    assert c_id not in {w.submission_id for w in result.winners}


async def test_vibing_submission_can_win(db_session):
    # Most Noted is participation-mode-agnostic.
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_round(db_session, organizer)
    sub_vibe = await _seed_submission(db_session, round_, member, title="Vibes", mode="vibing")
    sub_play = await _seed_submission(db_session, round_, organizer, title="Plays", mode="playing")
    round_id, vibe_id, play_id = round_.id, sub_vibe.id, sub_play.id

    await _add_note(db_session, round_id, vibe_id, organizer.id, "v1")
    await _add_note(db_session, round_id, vibe_id, member.id, "v2")
    await _add_note(db_session, round_id, play_id, organizer.id, "p1")

    result = await compute_most_noted(round_id, db_session)
    assert result.note_count == 2
    assert len(result.winners) == 1
    assert result.winners[0].submission_id == vibe_id
    assert result.winners[0].title == "Vibes"


async def test_counts_are_per_submission_not_global(db_session):
    # The winner's note_count reflects only its own notes, not the round total.
    organizer = await _seed_user(db_session, "o@example.com")
    member = await _seed_user(db_session, "m@example.com")
    round_ = await _seed_round(db_session, organizer)
    sub_win = await _seed_submission(db_session, round_, organizer, title="Winner")
    sub_other = await _seed_submission(db_session, round_, member, title="Other")
    round_id, win_id, other_id = round_.id, sub_win.id, sub_other.id

    await _add_note(db_session, round_id, win_id, organizer.id, "w1")
    await _add_note(db_session, round_id, win_id, member.id, "w2")
    await _add_note(db_session, round_id, win_id, member.id, "w3")
    await _add_note(db_session, round_id, other_id, organizer.id, "o1")

    result = await compute_most_noted(round_id, db_session)
    assert result.note_count == 3
    assert result.winners[0].submission_id == win_id
    assert result.winners[0].note_count == 3
    assert len(result.winners[0].notes) == 3
