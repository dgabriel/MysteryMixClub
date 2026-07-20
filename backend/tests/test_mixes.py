"""Tests for MYS-18: mix creation, read, and the state machine.

Covers auth/membership/organizer gates, sequential mix numbering and the
"close the current mix first" rule, the forward-only state machine
(open_submission -> open_voting -> closed) including invalid transitions, and
club completion when the final mix closes. Playlist generation is a
separate slice (depends on submissions, MYS-51) and is not exercised here.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.auth.jwt import create_access_token
from app.models.apple_mix_playlist import AppleMixPlaylist
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.note import Note
from app.models.mix import Mix
from app.models.spotify_mix_playlist import SpotifyMixPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club(
    db_session, organizer: User, *, total_mixes: int = 3, votes_per_player: int = 3
) -> Club:
    club = Club(
        name="Friday Mixtape",
        organizer_id=organizer.id,
        total_mixes=total_mixes,
        votes_per_player=votes_per_player,
    )
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    await db_session.commit()
    await db_session.refresh(club)
    return club


async def _add_member(db_session, club_id: uuid.UUID, user: User) -> None:
    db_session.add(ClubMember(club_id=club_id, user_id=user.id))
    await db_session.commit()


def _auth(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def _mixes_url(club_id: uuid.UUID) -> str:
    return f"/api/v1/clubs/{club_id}/mixes"


async def _create_mix(client, club_id, organizer_id, **body):
    body.setdefault("theme", "late summer feels")
    return await client.post(_mixes_url(club_id), json=body, headers=_auth(organizer_id))


async def _advance(client, mix_id, organizer_id, state):
    return await client.patch(
        f"/api/v1/mixes/{mix_id}", json={"state": state}, headers=_auth(organizer_id)
    )


# --------------------------------------------------------------------------- #
# Create — auth / authorization
# --------------------------------------------------------------------------- #


async def test_create_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    resp = await client.post(_mixes_url(club.id), json={"theme": "x"})
    assert resp.status_code == 401


async def test_create_non_organizer_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)

    resp = await client.post(_mixes_url(club.id), json={"theme": "x"}, headers=_auth(member.id))
    assert resp.status_code == 403


async def test_create_missing_theme_is_allowed(client, db_session):
    # theme is now optional (MYS-62): a mix may be created without one.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    resp = await client.post(_mixes_url(club.id), json={}, headers=_auth(organizer.id))
    assert resp.status_code == 201, resp.text
    assert resp.json()["theme"] is None


# --------------------------------------------------------------------------- #
# Create — happy paths + sequencing
# --------------------------------------------------------------------------- #


async def test_create_first_mix_defaults(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, votes_per_player=5)
    club_id = club.id

    resp = await _create_mix(client, club_id, organizer.id, theme="  golden hour  ")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mix_number"] == 1
    assert body["state"] == "open_submission"
    assert body["theme"] == "golden hour"  # trimmed
    assert body["votes_per_player"] == 5  # inherited from the club
    assert body["closed_at"] is None

    # The new mix becomes the club's active mix.
    db_session.expire_all()
    club = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert club.current_mix == 1


async def test_create_mix_votes_override(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, votes_per_player=3)
    resp = await _create_mix(client, club.id, organizer.id, votes_per_player=1)
    assert resp.status_code == 201
    assert resp.json()["votes_per_player"] == 1


async def test_cannot_create_second_mix_while_first_open(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    first = await _create_mix(client, club.id, organizer.id)
    assert first.status_code == 201

    second = await _create_mix(client, club.id, organizer.id)
    assert second.status_code == 409
    assert "closed" in second.json()["detail"]


async def test_sequential_numbering_after_closing(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=3)

    r1 = await _create_mix(client, club.id, organizer.id)
    rid1 = r1.json()["id"]
    assert (await _advance(client, rid1, organizer.id, "open_voting")).status_code == 200
    assert (await _advance(client, rid1, organizer.id, "closed")).status_code == 200

    r2 = await _create_mix(client, club.id, organizer.id)
    assert r2.status_code == 201
    assert r2.json()["mix_number"] == 2


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


async def test_list_mixes_ordered_for_member(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    await _create_mix(client, club.id, organizer.id, theme="one")

    resp = await client.get(_mixes_url(club.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    mixes = resp.json()
    assert [r["mix_number"] for r in mixes] == [1]


async def test_list_mixes_non_member_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    outsider = await _seed_user(db_session, "outsider@example.com")
    club = await _seed_club(db_session, organizer)
    resp = await client.get(_mixes_url(club.id), headers=_auth(outsider.id))
    assert resp.status_code == 403


async def test_get_mix_detail(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    created = await _create_mix(client, club.id, organizer.id, theme="the one that got away")
    rid = created.json()["id"]

    resp = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["theme"] == "the one that got away"


async def test_get_unknown_mix_404(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    await _seed_club(db_session, organizer)
    resp = await client.get(f"/api/v1/mixes/{uuid.uuid4()}", headers=_auth(organizer.id))
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #


async def test_full_forward_transitions(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=2)  # not the final mix
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    to_voting = await _advance(client, rid, organizer.id, "open_voting")
    assert to_voting.status_code == 200
    assert to_voting.json()["state"] == "open_voting"

    to_closed = await _advance(client, rid, organizer.id, "closed")
    assert to_closed.status_code == 200
    assert to_closed.json()["state"] == "closed"
    assert to_closed.json()["closed_at"] is not None


async def test_skipping_a_state_is_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    resp = await _advance(client, rid, organizer.id, "closed")  # skips open_voting
    assert resp.status_code == 409


async def test_closed_to_open_submission_is_rejected(client, db_session):
    # open_voting -> open_submission is now the MYS-168 sanctioned rollback (see
    # the dedicated "Rollback" section below), so it's no longer a backward
    # transition this test can use. closed -> open_submission is NOT the
    # sanctioned transition (the mix isn't in open_voting) and must still 409,
    # preserving the "forward-only except this one exception" invariant.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=2)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 409


async def test_open_submission_to_pending_is_rejected(client, db_session):
    # Another backward transition that is NOT the sanctioned rollback (the mix
    # is open_submission, not open_voting) — must still 409.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    resp = await _advance(client, rid, organizer.id, "pending")
    assert resp.status_code == 409


async def test_open_voting_to_pending_is_rejected(client, db_session):
    # MYS-168: the sanctioned rollback is open_voting -> open_submission only.
    # This pins the exact boolean in update_mix —
    # `is_rollback = mix_.state == "open_voting" and new_state == "open_submission"`
    # — proving a transition OUT of open_voting to anything else (e.g. pending)
    # is still rejected, not just the closed/open_submission cases covered above.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")

    resp = await _advance(client, rid, organizer.id, "pending")
    assert resp.status_code == 409


async def test_editing_closed_mix_is_rejected(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=2)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await client.patch(
        f"/api/v1/mixes/{rid}", json={"theme": "too late"}, headers=_auth(organizer.id)
    )
    assert resp.status_code == 409


async def test_patch_requires_organizer(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    resp = await client.patch(
        f"/api/v1/mixes/{rid}", json={"state": "open_voting"}, headers=_auth(member.id)
    )
    assert resp.status_code == 403


async def test_patch_updates_deadline_on_open_mix(client, db_session):
    # A mix created via single-create is born open_submission. Deadlines stay
    # editable until the mix closes, so a deadline-only edit still succeeds.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    deadline = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    resp = await client.patch(
        f"/api/v1/mixes/{rid}",
        json={"submission_deadline": deadline},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission_deadline"] is not None


async def test_patch_theme_on_open_mix_is_rejected(client, db_session):
    # theme is locked once a mix opens (MYS-62 edit lock). A single-created
    # mix is born open_submission, so editing its theme is a 409.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    resp = await client.patch(
        f"/api/v1/mixes/{rid}",
        json={"theme": "rainy day b-sides"},
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409, resp.text
    assert "locked" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Rollback: open_voting -> open_submission (MYS-168)
# --------------------------------------------------------------------------- #


async def test_rollback_happy_path_resets_deadlines_and_deletes_votes(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    # create_mix doesn't auto-stamp a submission_deadline (only advance/rollback
    # do), so set one explicitly here to stand in for the mix's "first pass"
    # deadline that the rollback must overwrite with a fresh full window.
    original_submission_deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    rid = (
        await _create_mix(
            client,
            club.id,
            organizer.id,
            submission_deadline=original_submission_deadline.isoformat(),
        )
    ).json()["id"]
    mix_id = uuid.UUID(rid)

    org_sub = await _add_submission_ret(db_session, mix_id, organizer)
    mem_sub = await _add_submission_ret(db_session, mix_id, member)

    assert (await _advance(client, rid, organizer.id, "open_voting")).status_code == 200

    await _add_vote(db_session, mix_id, organizer, mem_sub)
    await _add_vote(db_session, mix_id, member, org_sub)

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "open_submission"
    assert body["voting_deadline"] is None
    assert body["submission_deadline"] is not None

    new_deadline = datetime.fromisoformat(body["submission_deadline"])
    # A fresh full window, not the mix's original stale deadline.
    assert new_deadline > original_submission_deadline

    # The votes cast during the accidental voting phase are gone.
    db_session.expire_all()
    remaining_votes = (await db_session.scalars(select(Vote).where(Vote.mix_id == mix_id))).all()
    assert remaining_votes == []


async def test_rollback_supersedes_apple_playlists_but_keeps_spotify(client, db_session):
    """Reopening submissions supersedes Apple playlists so members can rebuild.

    Marked rather than deleted (MYS-108): the row is what tells a rebuild it's a
    revision, so it can name itself distinctly instead of leaving two
    same-named playlists in the member's library. Spotify must survive
    untouched — its generation refreshes the same playlist in place, so
    clearing it would orphan a public playlist and mint a duplicate.
    """
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    mix_id = uuid.UUID(rid)

    await _add_submission_ret(db_session, mix_id, organizer)
    await _add_submission_ret(db_session, mix_id, member)
    assert (await _advance(client, rid, organizer.id, "open_voting")).status_code == 200

    # Two members each built their own Apple playlist (they're per-user), plus a
    # shared-account Spotify playlist for the same mix.
    db_session.add(AppleMixPlaylist(mix_id=mix_id, user_id=organizer.id, playlist_id="p.ORG"))
    db_session.add(AppleMixPlaylist(mix_id=mix_id, user_id=member.id, playlist_id="p.MEM"))
    db_session.add(SpotifyMixPlaylist(mix_id=mix_id, user_id=organizer.id, playlist_id="sp1"))
    await db_session.commit()

    assert (await _advance(client, rid, organizer.id, "open_submission")).status_code == 200

    db_session.expire_all()
    apple_rows = (
        await db_session.scalars(select(AppleMixPlaylist).where(AppleMixPlaylist.mix_id == mix_id))
    ).all()
    spotify_rows = (
        await db_session.scalars(
            select(SpotifyMixPlaylist).where(SpotifyMixPlaylist.mix_id == mix_id)
        )
    ).all()

    # Both members' rows survive, all marked superseded — kept so a rebuild
    # knows it's a revision, hidden from the mix page so the CTA returns.
    assert len(apple_rows) == 2
    assert all(r.superseded_at is not None for r in apple_rows)
    assert sorted(r.playlist_id for r in apple_rows) == ["p.MEM", "p.ORG"]
    assert [r.playlist_id for r in spotify_rows] == ["sp1"]


async def test_rollback_preserves_notes(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    mix_id = uuid.UUID(rid)
    sub_id = await _add_submission_ret(db_session, mix_id, organizer)

    assert (await _advance(client, rid, organizer.id, "open_voting")).status_code == 200

    note_resp = await client.post(
        f"/api/v1/submissions/{sub_id}/notes",
        json={"body": "banger"},
        headers=_auth(organizer.id),
    )
    assert note_resp.status_code == 201, note_resp.text

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    notes = (await db_session.scalars(select(Note).where(Note.submission_id == sub_id))).all()
    assert len(notes) == 1
    assert notes[0].body == "banger"


async def test_rollback_rearms_warning_and_notice_timestamps(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    organizer_id = organizer.id  # capture before expire_all (MissingGreenlet trap)
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer_id)).json()["id"]
    mix_id = uuid.UUID(rid)

    assert (await _advance(client, rid, organizer_id, "open_voting")).status_code == 200

    db_session.expire_all()
    mix_ = await db_session.scalar(select(Mix).where(Mix.id == mix_id))
    now = datetime.now(timezone.utc)
    mix_.submission_warning_sent_at = now
    mix_.voting_warning_sent_at = now
    mix_.empty_round_notice_sent_at = now
    db_session.add(mix_)
    await db_session.commit()

    resp = await _advance(client, rid, organizer_id, "open_submission")
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    after = await db_session.scalar(select(Mix).where(Mix.id == mix_id))
    assert after.submission_warning_sent_at is None
    assert after.voting_warning_sent_at is None
    assert after.empty_round_notice_sent_at is None


async def test_rollback_rejected_when_mix_is_closed(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=2)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 409


async def test_rollback_no_op_when_mix_already_open_submission(client, db_session):
    # PATCHing state=open_submission on a mix that's already open_submission is
    # a same-state no-op (the state-transition block is only entered when
    # new_state != mix_.state) — it succeeds (200), it is not a rollback
    # attempt to reject. Documented here so the invariant isn't mistaken for a
    # 409 case in future changes.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 200
    assert resp.json()["state"] == "open_submission"


async def test_rollback_requires_organizer(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")

    resp = await client.patch(
        f"/api/v1/mixes/{rid}", json={"state": "open_submission"}, headers=_auth(member.id)
    )
    assert resp.status_code == 403


async def test_rollback_does_not_spuriously_conflict_with_active_mix_guard(client, db_session):
    # The "only one mix active per club" guard must not fire against a
    # mix rolling back to its own prior state — even if (hypothetically) a
    # second mix were also active in the same club, the rollback of the
    # first is exempt from that guard.
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=3)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    assert (await _advance(client, rid, organizer.id, "open_voting")).status_code == 200

    other_mix = Mix(club_id=club.id, mix_number=2, state="open_submission")
    db_session.add(other_mix)
    await db_session.commit()

    resp = await _advance(client, rid, organizer.id, "open_submission")
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "open_submission"


# --------------------------------------------------------------------------- #
# Club completion
# --------------------------------------------------------------------------- #


async def test_closing_final_mix_completes_club(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=1)
    club_id = club.id
    rid = (await _create_mix(client, club_id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    db_session.expire_all()
    club = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert club.state == "complete"
    assert club.completed_at is not None


async def test_closing_nonfinal_mix_does_not_complete_club(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=2)
    club_id = club.id
    rid = (await _create_mix(client, club_id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    db_session.expire_all()
    club = await db_session.scalar(select(Club).where(Club.id == club_id))
    assert club.state == "active"
    assert club.completed_at is None


async def test_cannot_create_mix_on_complete_club(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=1)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    await _advance(client, rid, organizer.id, "closed")

    resp = await _create_mix(client, club.id, organizer.id)
    assert resp.status_code == 409
    assert "wrapped" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# Submission progress (MYS-101)
# --------------------------------------------------------------------------- #


async def _add_submission(db_session, mix_id: uuid.UUID, user: User) -> None:
    db_session.add(
        Submission(
            mix_id=mix_id,
            user_id=user.id,
            isrc=f"ISRC-{user.id}",
            title="A song",
            artist="An artist",
            participation_mode="playing",
        )
    )
    await db_session.commit()


async def test_mix_reports_submission_and_member_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    other = await _seed_user(db_session, "other@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    await _add_member(db_session, club.id, other)

    # A fresh mix on creation has no submissions yet but knows the member count.
    created = (await _create_mix(client, club.id, organizer.id)).json()
    rid = created["id"]
    assert created["submission_count"] == 0
    assert created["member_count"] == 3

    await _add_submission(db_session, uuid.UUID(rid), organizer)

    detail = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["submission_count"] == 1  # 3 members, 1 has submitted
    assert body["member_count"] == 3


async def test_list_mixes_includes_per_mix_submission_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer, total_mixes=3)
    await _add_member(db_session, club.id, member)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _add_submission(db_session, uuid.UUID(rid), organizer)
    await _add_submission(db_session, uuid.UUID(rid), member)

    resp = await client.get(_mixes_url(club.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    by_number = {r["mix_number"]: r for r in resp.json()}
    assert by_number[1]["submission_count"] == 2
    assert by_number[1]["member_count"] == 2


async def test_submission_count_is_distinct_submitters(client, db_session):
    # A player with several songs (MYS-116) still counts once: submission_count
    # is distinct people, not rows.
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    # Organizer submits two songs; member submits one — two distinct submitters.
    await _add_submission(db_session, uuid.UUID(rid), organizer)
    await _add_submission(db_session, uuid.UUID(rid), organizer)
    await _add_submission(db_session, uuid.UUID(rid), member)

    detail = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    assert detail.status_code == 200, detail.text
    assert detail.json()["submission_count"] == 2  # 3 songs, 2 people


# --------------------------------------------------------------------------- #
# Voting progress (MYS-110)
# --------------------------------------------------------------------------- #


async def _add_vote(db_session, mix_id: uuid.UUID, voter: User, submission_id: uuid.UUID) -> None:
    db_session.add(Vote(mix_id=mix_id, voter_id=voter.id, submission_id=submission_id))
    await db_session.commit()


async def _add_submission_ret(
    db_session, mix_id: uuid.UUID, user: User, mode: str = "playing"
) -> uuid.UUID:
    sub = Submission(
        mix_id=mix_id,
        user_id=user.id,
        isrc=f"ISRC-{uuid.uuid4()}",
        title="A song",
        artist="An artist",
        participation_mode=mode,
    )
    db_session.add(sub)
    await db_session.commit()
    await db_session.refresh(sub)
    return sub.id


async def test_mix_reports_zero_voted_counts_before_voting(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]

    detail = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    body = detail.json()
    assert body["voted_count"] == 0
    assert body["voting_eligible_count"] == 0


async def test_mix_reports_voted_and_eligible_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    mix_id = uuid.UUID(rid)

    org_sub = await _add_submission_ret(db_session, mix_id, organizer)
    mem_sub = await _add_submission_ret(db_session, mix_id, member)

    # Both playing — eligible count should be 2, voted count 0 before any votes.
    detail = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    body = detail.json()
    assert body["voting_eligible_count"] == 2
    assert body["voted_count"] == 0

    # Organizer casts a vote for member's song.
    await _add_vote(db_session, mix_id, organizer, mem_sub)

    detail2 = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    body2 = detail2.json()
    assert body2["voting_eligible_count"] == 2
    assert body2["voted_count"] == 1

    # Member votes too — both have voted.
    await _add_vote(db_session, mix_id, member, org_sub)

    detail3 = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(member.id))
    body3 = detail3.json()
    assert body3["voted_count"] == 2


async def test_voting_eligible_excludes_vibing_submitters(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    viber = await _seed_user(db_session, "viber@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, viber)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    mix_id = uuid.UUID(rid)

    await _add_submission_ret(db_session, mix_id, organizer, mode="playing")
    await _add_submission_ret(db_session, mix_id, viber, mode="vibing")

    detail = await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))
    body = detail.json()
    # Only the playing submitter counts as eligible; the viber is excluded.
    assert body["voting_eligible_count"] == 1
    assert body["voted_count"] == 0


async def test_list_mixes_includes_voted_counts(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)

    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    mix_id = uuid.UUID(rid)

    await _add_submission_ret(db_session, mix_id, organizer)
    mem_sub = await _add_submission_ret(db_session, mix_id, member)
    await _add_vote(db_session, mix_id, organizer, mem_sub)

    resp = await client.get(_mixes_url(club.id), headers=_auth(member.id))
    assert resp.status_code == 200, resp.text
    by_number = {r["mix_number"]: r for r in resp.json()}
    assert by_number[1]["voting_eligible_count"] == 2
    assert by_number[1]["voted_count"] == 1


# --------------------------------------------------------------------------- #
# Extend voting deadline (MYS-180)
# --------------------------------------------------------------------------- #


def _extend_url(mix_id) -> str:
    return f"/api/v1/mixes/{mix_id}/extend-voting"


def _extend_body(deadline: datetime) -> dict:
    return {"voting_deadline": deadline.isoformat()}


async def test_extend_voting_requires_auth(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    resp = await client.post(
        _extend_url(rid), json=_extend_body(datetime.now(timezone.utc) + timedelta(hours=4))
    )
    assert resp.status_code == 401


async def test_extend_voting_non_organizer_forbidden(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    member = await _seed_user(db_session, "member@example.com")
    club = await _seed_club(db_session, organizer)
    await _add_member(db_session, club.id, member)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")

    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(datetime.now(timezone.utc) + timedelta(hours=4)),
        headers=_auth(member.id),
    )
    assert resp.status_code == 403


async def test_extend_voting_wrong_state_409(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    # Mix is open_submission, not open_voting yet.
    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(datetime.now(timezone.utc) + timedelta(hours=4)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 409


async def test_extend_voting_to_chosen_deadline(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    before = (await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))).json()
    old_deadline = datetime.fromisoformat(before["voting_deadline"])
    chosen = old_deadline + timedelta(hours=20)

    resp = await client.post(
        _extend_url(rid), json=_extend_body(chosen), headers=_auth(organizer.id)
    )
    assert resp.status_code == 200, resp.text
    new_deadline = datetime.fromisoformat(resp.json()["voting_deadline"])
    assert new_deadline == chosen


async def test_extend_voting_is_repeatable(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    before = (await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))).json()
    old_deadline = datetime.fromisoformat(before["voting_deadline"])

    await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline + timedelta(hours=4)),
        headers=_auth(organizer.id),
    )
    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline + timedelta(hours=8)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text
    new_deadline = datetime.fromisoformat(resp.json()["voting_deadline"])
    assert new_deadline == old_deadline + timedelta(hours=8)


async def test_extend_voting_rejects_deadline_not_after_current(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    before = (await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))).json()
    old_deadline = datetime.fromisoformat(before["voting_deadline"])

    resp = await client.post(
        _extend_url(rid), json=_extend_body(old_deadline), headers=_auth(organizer.id)
    )
    assert resp.status_code == 422

    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline - timedelta(hours=1)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 422


async def test_extend_voting_rejects_deadline_beyond_48h(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    before = (await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))).json()
    old_deadline = datetime.fromisoformat(before["voting_deadline"])

    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline + timedelta(hours=48, minutes=1)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 422

    # Exactly the boundary is fine.
    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline + timedelta(hours=48)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text


async def test_extend_voting_resets_warning_marker(client, db_session):
    organizer = await _seed_user(db_session, "org@example.com")
    club = await _seed_club(db_session, organizer)
    rid = (await _create_mix(client, club.id, organizer.id)).json()["id"]
    await _advance(client, rid, organizer.id, "open_voting")
    mix_id = uuid.UUID(rid)

    mix_ = await db_session.get(Mix, mix_id)
    mix_.voting_warning_sent_at = datetime.now(timezone.utc)
    await db_session.commit()

    before = (await client.get(f"/api/v1/mixes/{rid}", headers=_auth(organizer.id))).json()
    old_deadline = datetime.fromisoformat(before["voting_deadline"])
    resp = await client.post(
        _extend_url(rid),
        json=_extend_body(old_deadline + timedelta(hours=4)),
        headers=_auth(organizer.id),
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    refreshed = await db_session.get(Mix, mix_id)
    assert refreshed.voting_warning_sent_at is None
