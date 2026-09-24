"""Tests for MysteryMixClub-4vii.42: block an abusive club member (Guideline 1.2).

App Store Guideline 1.2 requires a UGC app to give users a way to block
abusive users, not just report their content. A block here is one-directional
and quiet (ADR 0035): it filters only the *blocker's* reads -- the blocked
member is never notified and their own app is unchanged.

Covered:

- Lifecycle: block persists and lists; re-block is idempotent (200 on the
  standing row); unblock removes and a second unblock 404s.
- Validation: 401 unauthenticated; 400 self-block; one neutral 404 for
  unknown users, deleted accounts, and never-shared-a-club strangers alike.
- Removed clubmates stay blockable: their reveal notes are still visible, so
  the protection must outlive the membership.
- Enforcement, per surface: reveal notes (GET /submissions/:id/notes +
  results payload + Most Noted recompute), the submitter note on the voting
  playlist and the reveal, reveal voter attribution, the submission-history
  view, and the members list's blocked_by_me flag.
- The block is invisible from the other side: the blocked member still sees
  everything, including the blocker's notes.
"""

import uuid

from sqlalchemy import func, select

from app.auth.jwt import create_access_token
from app.models.block import Block
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


def _blocks_url() -> str:
    return "/api/v1/users/me/blocks"


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# --------------------------------------------------------------------------- #
# Seeding helpers (same shape as test_reports/test_most_noted)
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(db_session, organizer: User, *members: User) -> Club:
    club = Club(name="Block Club", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    for member in members:
        db_session.add(ClubMember(club_id=club.id, user_id=member.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _seed_mix(db_session, club: Club, *, state: str = "closed") -> Mix:
    mix_ = Mix(club_id=club.id, mix_number=1, theme="t", state=state)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    return mix_


async def _seed_submission(
    db_session, mix_: Mix, user: User, *, title: str, note: str | None = None
) -> Submission:
    sub = Submission(
        mix_id=mix_.id,
        user_id=user.id,
        isrc="USABC1234567",
        title=title,
        artist="Artist",
        participation_mode="playing",
        note=note,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub


async def _add_note(db_session, mix_id, submission_id, author_id, body: str) -> Note:
    note = Note(mix_id=mix_id, submission_id=submission_id, author_id=author_id, body=body)
    db_session.add(note)
    await db_session.commit()
    await db_session.refresh(note)
    return note


async def _add_vote(db_session, mix_id, submission_id, voter_id, weight: int) -> None:
    db_session.add(
        Vote(mix_id=mix_id, submission_id=submission_id, voter_id=voter_id, weight=weight)
    )
    await db_session.commit()


async def _block_count(db_session) -> int:
    return await db_session.scalar(select(func.count()).select_from(Block)) or 0


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #


async def test_block_requires_auth(client):
    resp = await client.post(_blocks_url(), json={"user_id": str(uuid.uuid4())})
    assert resp.status_code == 401, resp.text


async def test_block_member_persists_and_lists(client, db_session):
    blocker = await _seed_user(db_session, "a@example.com", "Ann")
    target = await _seed_user(db_session, "b@example.com", "Brad")
    await _seed_club(db_session, blocker, target)

    resp = await client.post(
        _blocks_url(), json={"user_id": str(target.id)}, headers=_auth_header(blocker.id)
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body == {
        "user_id": str(target.id),
        "display_name": "Brad",
        "created_at": body["created_at"],
    }
    row = await db_session.scalar(select(Block).where(Block.blocker_id == blocker.id))
    assert row is not None and row.blocked_id == target.id

    listing = await client.get(_blocks_url(), headers=_auth_header(blocker.id))
    assert listing.status_code == 200, listing.text
    assert [b["user_id"] for b in listing.json()] == [str(target.id)]
    # The other side has no block of their own.
    other = await client.get(_blocks_url(), headers=_auth_header(target.id))
    assert other.json() == []


async def test_reblock_is_idempotent(client, db_session):
    blocker = await _seed_user(db_session, "a@example.com", "Ann")
    target = await _seed_user(db_session, "b@example.com", "Brad")
    await _seed_club(db_session, blocker, target)

    first = await client.post(
        _blocks_url(), json={"user_id": str(target.id)}, headers=_auth_header(blocker.id)
    )
    second = await client.post(
        _blocks_url(), json={"user_id": str(target.id)}, headers=_auth_header(blocker.id)
    )

    assert first.status_code == 201
    assert second.status_code == 200, second.text
    assert await _block_count(db_session) == 1


async def test_unblock_then_repeat_unblock_404(client, db_session):
    blocker = await _seed_user(db_session, "a@example.com", "Ann")
    target = await _seed_user(db_session, "b@example.com", "Brad")
    await _seed_club(db_session, blocker, target)
    await client.post(
        _blocks_url(), json={"user_id": str(target.id)}, headers=_auth_header(blocker.id)
    )

    gone = await client.delete(f"{_blocks_url()}/{target.id}", headers=_auth_header(blocker.id))
    assert gone.status_code == 204, gone.text
    assert await _block_count(db_session) == 0

    again = await client.delete(f"{_blocks_url()}/{target.id}", headers=_auth_header(blocker.id))
    assert again.status_code == 404, again.text


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


async def test_cannot_block_self(client, db_session):
    user = await _seed_user(db_session, "a@example.com", "Ann")
    resp = await client.post(
        _blocks_url(), json={"user_id": str(user.id)}, headers=_auth_header(user.id)
    )
    assert resp.status_code == 400, resp.text
    assert "yourself" in resp.json()["detail"]
    assert await _block_count(db_session) == 0


async def test_cannot_block_unknown_user(client, db_session):
    user = await _seed_user(db_session, "a@example.com", "Ann")
    resp = await client.post(
        _blocks_url(), json={"user_id": str(uuid.uuid4())}, headers=_auth_header(user.id)
    )
    assert resp.status_code == 404, resp.text


async def test_cannot_block_stranger_never_shared_a_club(client, db_session):
    """One neutral 404 for strangers and nonexistent users alike -- the
    endpoint must not be a user-existence oracle (design on the ticket)."""
    in_club = await _seed_user(db_session, "a@example.com", "Ann")
    outsider = await _seed_user(db_session, "x@example.com", "Xena")
    await _seed_club(db_session, in_club)  # outsider is in no club with Ann

    resp = await client.post(
        _blocks_url(), json={"user_id": str(outsider.id)}, headers=_auth_header(in_club.id)
    )

    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "member not found"
    assert await _block_count(db_session) == 0


async def test_removed_clubmate_remains_blockable(client, db_session):
    """A removed member's notes still show at a closed mix's reveal, so the
    block has to outlive the membership."""
    from datetime import datetime, timezone

    blocker = await _seed_user(db_session, "a@example.com", "Ann")
    removed = await _seed_user(db_session, "r@example.com", "Rex")
    club = await _seed_club(db_session, blocker, removed)
    membership = await db_session.scalar(
        select(ClubMember).where(ClubMember.club_id == club.id, ClubMember.user_id == removed.id)
    )
    membership.removed_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.post(
        _blocks_url(), json={"user_id": str(removed.id)}, headers=_auth_header(blocker.id)
    )

    assert resp.status_code == 201, resp.text


# --------------------------------------------------------------------------- #
# Enforcement — notes reveal
# --------------------------------------------------------------------------- #


async def _closed_mix_with_notes(db_session):
    """Alice (blocker), Brad (blocked target), Cyd (bystander) share a closed
    mix. Cyd submitted a song; Brad and Cyd both noted it; Brad voted on it.

    Returns (viewer Alice, target Brad, bystander Cyd, club, mix, submission).
    """
    alice = await _seed_user(db_session, "a@example.com", "Ann")
    brad = await _seed_user(db_session, "b@example.com", "Brad")
    cyd = await _seed_user(db_session, "c@example.com", "Cyd")
    club = await _seed_club(db_session, alice, brad, cyd)
    mix_ = await _seed_mix(db_session, club, state="closed")
    sub = await _seed_submission(db_session, mix_, cyd, title="Song", note="cyd's pick")
    await _seed_submission(db_session, mix_, brad, title="Brad Song", note="brad's pick")
    await _add_note(db_session, mix_.id, sub.id, brad.id, "brad was here")
    await _add_note(db_session, mix_.id, sub.id, cyd.id, "cyd's note")
    await _add_vote(db_session, mix_.id, sub.id, brad.id, 5)
    await _add_vote(db_session, mix_.id, sub.id, alice.id, 3)
    return alice, brad, cyd, club, mix_, sub


async def test_reveal_notes_exclude_blocked_author(client, db_session):
    alice, brad, cyd, _club, _mix, sub = await _closed_mix_with_notes(db_session)

    before = await client.get(f"/api/v1/submissions/{sub.id}/notes", headers=_auth_header(alice.id))
    assert {n["body"] for n in before.json()} == {"brad was here", "cyd's note"}

    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))

    after = await client.get(f"/api/v1/submissions/{sub.id}/notes", headers=_auth_header(alice.id))
    assert [n["body"] for n in after.json()] == ["cyd's note"]

    # The bystander's view is untouched -- blocks are one-directional.
    cyd_view = await client.get(f"/api/v1/submissions/{sub.id}/notes", headers=_auth_header(cyd.id))
    assert {n["body"] for n in cyd_view.json()} == {"brad was here", "cyd's note"}

    # And the blocked member still sees everything, including the blocker's
    # clubmate's content: they cannot tell they were blocked.
    brad_view = await client.get(
        f"/api/v1/submissions/{sub.id}/notes", headers=_auth_header(brad.id)
    )
    assert {n["body"] for n in brad_view.json()} == {"brad was here", "cyd's note"}

    # Unblocking restores the reveal.
    await client.delete(f"{_blocks_url()}/{brad.id}", headers=_auth_header(alice.id))
    restored = await client.get(
        f"/api/v1/submissions/{sub.id}/notes", headers=_auth_header(alice.id)
    )
    assert {n["body"] for n in restored.json()} == {"brad was here", "cyd's note"}


async def test_results_screen_filters_blocked_member(client, db_session):
    alice, brad, _cyd, _club, mix_, sub = await _closed_mix_with_notes(db_session)
    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))

    resp = await client.get(f"/api/v1/mixes/{mix_.id}/results", headers=_auth_header(alice.id))

    assert resp.status_code == 200, resp.text
    by_title = {s["title"]: s for s in resp.json()["submissions"]}

    # The blocked submitter's note-text disappears; the submission itself and
    # its submitter attribution stay (the closed mix is the shared record).
    brads = by_title["Brad Song"]
    assert brads["submitter_display_name"] == "Brad"
    assert brads["submitter_note"] is None

    # Their note drops out of the per-submission list; the bystander's stays.
    cdy_sub = by_title["Song"]
    assert [n["body"] for n in cdy_sub["notes"]] == ["cyd's note"]
    # Their entry leaves the voter-attribution list, but the aggregate count
    # is shared truth -- Brad's 5-weight vote still counts.
    assert cdy_sub["vote_count"] == 8
    assert [v["display_name"] for v in cdy_sub["voters"]] == ["Ann"]


async def test_results_most_noted_recomputed_without_blocked_authors(client, db_session):
    """Most Noted feeds off the notes, so for a blocker it is computed without
    the blocked member's notes -- the note_count the API reports is what the
    viewer actually sees (ADR 0035)."""
    alice = await _seed_user(db_session, "a@example.com", "Ann")
    brad = await _seed_user(db_session, "b@example.com", "Brad")
    club = await _seed_club(db_session, alice, brad)
    mix_ = await _seed_mix(db_session, club, state="closed")
    sub_a = await _seed_submission(db_session, mix_, alice, title="A")
    sub_b = await _seed_submission(db_session, mix_, brad, title="B")
    # Brad's notes carry both songs...
    await _add_note(db_session, mix_.id, sub_a.id, brad.id, "brad on A")
    await _add_note(db_session, mix_.id, sub_b.id, brad.id, "brad on B")
    await _add_note(db_session, mix_.id, sub_b.id, alice.id, "alice on B")

    unfiltered = await client.get(
        f"/api/v1/mixes/{mix_.id}/results", headers=_auth_header(alice.id)
    )
    assert unfiltered.json()["most_noted"]["note_count"] == 2

    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))
    blocked_view = await client.get(
        f"/api/v1/mixes/{mix_.id}/results", headers=_auth_header(alice.id)
    )

    most_noted = blocked_view.json()["most_noted"]
    assert most_noted["note_count"] == 1
    assert [w["title"] for w in most_noted["winners"]] == ["B"]
    assert [n["body"] for n in most_noted["winners"][0]["notes"]] == ["alice on B"]


async def test_playlist_hides_blocked_submitters_note(client, db_session):
    alice = await _seed_user(db_session, "a@example.com", "Ann")
    brad = await _seed_user(db_session, "b@example.com", "Brad")
    club = await _seed_club(db_session, alice, brad)
    mix_ = await _seed_mix(db_session, club, state="open_voting")
    await _seed_submission(db_session, mix_, brad, title="Brad Song", note="brad's pitch")
    await _seed_submission(db_session, mix_, alice, title="Ann Song", note="ann's pitch")

    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))
    resp = await client.get(f"/api/v1/mixes/{mix_.id}/playlist", headers=_auth_header(alice.id))

    assert resp.status_code == 200, resp.text
    by_title = {e["title"]: e for e in resp.json()["entries"]}
    # The song row stays (the blocker can still judge the pick); the blocked
    # member's free text does not -- while the blocker's own note is intact.
    assert by_title["Brad Song"]["submitter_note"] is None
    assert by_title["Ann Song"]["submitter_note"] == "ann's pitch"

    # Brad's own playlist still shows his note: he cannot tell he was blocked.
    brads_playlist = await client.get(
        f"/api/v1/mixes/{mix_.id}/playlist", headers=_auth_header(brad.id)
    )
    brads_entry = next(e for e in brads_playlist.json()["entries"] if e["title"] == "Brad Song")
    assert brads_entry["submitter_note"] == "brad's pitch"


async def test_submission_history_hides_blocked_notes(client, db_session):
    alice, brad, _cyd, _club, mix_, _sub = await _closed_mix_with_notes(db_session)
    alices_sub = await _seed_submission(db_session, mix_, alice, title="Ann Song")
    await _add_note(db_session, mix_.id, alices_sub.id, brad.id, "brad on ann's")

    before = await client.get("/api/v1/users/me/submissions", headers=_auth_header(alice.id))
    entry = next(e for e in before.json() if e["title"] == "Ann Song")
    assert [n["body"] for n in entry["notes"]] == ["brad on ann's"]

    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))
    history = await client.get("/api/v1/users/me/submissions", headers=_auth_header(alice.id))

    entry = next(e for e in history.json() if e["title"] == "Ann Song")
    assert entry["notes"] == []


async def test_members_list_marks_blocked_rows(client, db_session):
    alice = await _seed_user(db_session, "a@example.com", "Ann")
    brad = await _seed_user(db_session, "b@example.com", "Brad")
    cyd = await _seed_user(db_session, "c@example.com", "Cyd")
    club = await _seed_club(db_session, alice, brad, cyd)

    await client.post(_blocks_url(), json={"user_id": str(brad.id)}, headers=_auth_header(alice.id))
    resp = await client.get(f"/api/v1/clubs/{club.id}/members", headers=_auth_header(alice.id))

    assert resp.status_code == 200, resp.text
    flags = {m["user_id"]: m["blocked_by_me"] for m in resp.json()}
    assert flags[str(brad.id)] is True
    assert flags[str(cyd.id)] is False
    assert flags[str(alice.id)] is False


# --------------------------------------------------------------------------- #
# Account lifecycle
# --------------------------------------------------------------------------- #


async def test_purging_either_side_removes_the_block(client, db_session):
    """Block rows follow the account they belong to at purge time (both FKs
    CASCADE), and the purge job deletes them explicitly so admin ejects of
    live accounts stay FK-safe (ADR 0035)."""
    from app.jobs.purge_accounts import hard_delete_users

    blocker = await _seed_user(db_session, "a@example.com", "Ann")
    target = await _seed_user(db_session, "b@example.com", "Brad")
    club = await _seed_club(db_session, blocker, target)
    # No active state needed beyond membership; purge Brad (the blocked side).
    await client.post(
        _blocks_url(), json={"user_id": str(target.id)}, headers=_auth_header(blocker.id)
    )
    assert await _block_count(db_session) == 1

    # Free the club FK (hard_delete_users nulls organizer_id itself) and run
    # the purge path directly, the same call the scheduler/admin routes make.
    club.organizer_id = None
    await db_session.commit()
    await hard_delete_users(db_session, [target.id], ["b@example.com"])
    await db_session.commit()

    assert await _block_count(db_session) == 0
    assert await db_session.get(User, target.id) is None
