"""Tests for MysteryMixClub-4vii.43: content filtering method for free-text
notes (Guideline 1.2).

An App Store UGC app must "filter objectionable material", not just report it
after the fact. The mechanism (ADR 0036, app/services/content_filter.py) is a
curated denylist enforced at WRITE on every member-visible free-text surface,
with text normalized first (accents off, leetspeak mapped, repeated letters
collapsed) so the cheapest evasions die too.

Covered:

- The matcher: exact/plural hits, casing, leetspeak, repeated-letter and
  accented evasions, multi-word harassment phrases; and the Scunthorpe-family
  false positives that must PASS (bass, class, assassin, Scunthorpe).
- Every filtered surface 422s a flagged write with the one generic
  CONTENT_POLICY_MESSAGE (the flagged term is never echoed), while a clean
  write still succeeds: display name, club name/description (create + patch),
  mix theme/description, submission note (create / replace / note-only edit),
  note body (create + edit).
- Unfiltered surfaces stay open: report detail (operators-only audience) and
  catalog song fields are not flagged even when spicy-looking.
"""

import uuid

from app.auth.jwt import create_access_token
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User
from app.services.content_filter import CONTENT_POLICY_MESSAGE, find_denied_term

# A mid-severity list entry used across the route tests. (The matcher is
# agnostic to which entry trips; one stable term keeps fixtures readable.)
_FLAGGED = "retard"


# --------------------------------------------------------------------------- #
# Unit: normalization + matching
# --------------------------------------------------------------------------- #


def test_flags_exact_and_plural_and_case():
    assert find_denied_term("retard") == _FLAGGED
    assert find_denied_term("You RETARDS ruined this") == _FLAGGED


def test_flags_leetspeak_and_punctuation_evasions():
    assert find_denied_term("r3t@rd") == _FLAGGED
    assert find_denied_term("r.e.t.a.r.d") == _FLAGGED
    assert find_denied_term("R3T4RD!!") == _FLAGGED


def test_flags_repeated_letters_and_accents():
    # "retaaard" collapses under the run-compression rule.
    assert find_denied_term("retaaard") == _FLAGGED
    assert find_denied_term("kïll yöurself") == "kill yourself"


def test_flags_harassment_phrase():
    assert find_denied_term("just kill yourself already") == "kill yourself"
    assert find_denied_term("kys loser") == "kys"


def test_scunthorpe_family_passes():
    # The word-exact rule exists for these: song talk is full of them.
    for benign in (
        "bass",
        "bassist",
        "class",
        "classic",
        "assassin by muse",
        "kickass riff",
        "amazing brass section",
        "this song is the tits",  # not on the list — allowed register
        "Scunthorpe united anthem",
        "cumulonimbus skies",  # shares a prefix with a listed term
    ):
        assert find_denied_term(benign) is None, benign


def test_clean_text_passes():
    assert find_denied_term("this absolutely slaps, what a pick") is None
    assert find_denied_term("") is None


# --------------------------------------------------------------------------- #
# Route tests: each filtered surface rejects, and still accepts clean text
# --------------------------------------------------------------------------- #


def _auth_header(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


async def _seed_user(db_session, email: str, name: str = "User") -> User:
    user = User(email=email, display_name=name)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _seed_club_with_mix(
    db_session, organizer: User, member: User, *, mix_state: str = "open_submission"
) -> tuple[Club, Mix]:
    club = Club(name="Filter Club", organizer_id=organizer.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=organizer.id))
    if member.id != organizer.id:
        db_session.add(ClubMember(club_id=club.id, user_id=member.id))
    mix_ = Mix(club_id=club.id, mix_number=1, theme="first mystery mix", state=mix_state)
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(club)
    await db_session.refresh(mix_)
    return club, mix_


async def test_display_name_rejects_flagged_text(client, db_session):
    user = await _seed_user(db_session, "a@example.com", "Ann")

    resp = await client.patch(
        "/api/v1/users/me",
        headers=_auth_header(user.id),
        json={"display_name": f"{_FLAGGED} ann"},
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == CONTENT_POLICY_MESSAGE
    assert _FLAGGED not in resp.text

    ok = await client.patch(
        "/api/v1/users/me", headers=_auth_header(user.id), json={"display_name": "ann b"}
    )
    assert ok.status_code == 200, ok.text


async def test_club_create_and_patch_reject_flagged_text(client, db_session):
    user = await _seed_user(db_session, "b@example.com", "Ben")

    resp = await client.post(
        "/api/v1/clubs",
        headers=_auth_header(user.id),
        json={"name": f"the {_FLAGGED} club", "total_mixes": 3},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == CONTENT_POLICY_MESSAGE

    resp = await client.post(
        "/api/v1/clubs",
        headers=_auth_header(user.id),
        json={"name": "fine name", "description": f"no {_FLAGGED}s", "total_mixes": 3},
    )
    assert resp.status_code == 422, resp.text

    ok = await client.post(
        "/api/v1/clubs",
        headers=_auth_header(user.id),
        json={"name": "friday mixtape", "total_mixes": 3},
    )
    assert ok.status_code == 201, ok.text
    club_id = ok.json()["id"]

    patched = await client.patch(
        f"/api/v1/clubs/{club_id}",
        headers=_auth_header(user.id),
        json={"description": f"about {_FLAGGED}s"},
    )
    assert patched.status_code == 422, patched.text

    ok_patch = await client.patch(
        f"/api/v1/clubs/{club_id}",
        headers=_auth_header(user.id),
        json={"description": "about songs we love"},
    )
    assert ok_patch.status_code == 200, ok_patch.text


async def test_mix_theme_and_description_reject_flagged_text(client, db_session):
    organizer = await _seed_user(db_session, "c@example.com", "Cleo")
    _club, mix_ = await _seed_club_with_mix(db_session, organizer, organizer, mix_state="pending")
    headers = _auth_header(organizer.id)

    resp = await client.patch(
        f"/api/v1/mixes/{mix_.id}", headers=headers, json={"theme": f"{_FLAGGED} anthem"}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == CONTENT_POLICY_MESSAGE

    resp = await client.patch(
        f"/api/v1/mixes/{mix_.id}", headers=headers, json={"description": f"{_FLAGGED} vibes"}
    )
    assert resp.status_code == 422, resp.text

    ok = await client.patch(
        f"/api/v1/mixes/{mix_.id}", headers=headers, json={"theme": "songs that slap"}
    )
    assert ok.status_code == 200, ok.text


_SONG = {
    "isrc": "USABC1234567",
    "title": "Debaser",
    "artist": "Pixies",
}


async def test_submission_note_rejects_flagged_text(client, db_session):
    member = await _seed_user(db_session, "d@example.com", "Dell")
    _club, mix_ = await _seed_club_with_mix(db_session, member, member)
    headers = _auth_header(member.id)
    url = f"/api/v1/mixes/{mix_.id}/submissions"

    resp = await client.post(url, headers=headers, json={**_SONG, "note": f"for {_FLAGGED}s"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == CONTENT_POLICY_MESSAGE
    assert _FLAGGED not in resp.text

    ok = await client.post(url, headers=headers, json={**_SONG, "note": "an all-timer"})
    assert ok.status_code == 201, ok.text
    submission_id = ok.json()["id"]

    # Note-only edit is filtered too (MYS-150 route).
    resp = await client.patch(
        f"{url}/{submission_id}/note", headers=headers, json={"note": f"{_FLAGGED} city"}
    )
    assert resp.status_code == 422, resp.text

    # Wholesale replace is filtered too (same payload model as create).
    resp = await client.patch(
        f"{url}/{submission_id}",
        headers=headers,
        json={**_SONG, "note": f"{_FLAGGED} forever"},
    )
    assert resp.status_code == 422, resp.text

    cleared = await client.patch(
        f"{url}/{submission_id}/note", headers=headers, json={"note": "changed my mind, all-timer"}
    )
    assert cleared.status_code == 200, cleared.text


async def test_note_create_and_edit_reject_flagged_text(client, db_session):
    author = await _seed_user(db_session, "e@example.com", "Eli")
    other = await _seed_user(db_session, "f@example.com", "Fay")
    _club, mix_ = await _seed_club_with_mix(db_session, author, other, mix_state="open_voting")
    submission = Submission(
        mix_id=mix_.id,
        user_id=other.id,
        isrc="USABC1234567",
        title="Tame",
        artist="Impalers",
        participation_mode="playing",
    )
    db_session.add(submission)
    await db_session.commit()

    url = f"/api/v1/submissions/{submission.id}/notes"
    headers = _auth_header(author.id)

    resp = await client.post(url, headers=headers, json={"body": f"{_FLAGGED} take"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == CONTENT_POLICY_MESSAGE

    ok = await client.post(url, headers=headers, json={"body": "quietly perfect"})
    assert ok.status_code == 201, ok.text

    edited = await client.patch(url, headers=headers, json={"body": f"{_FLAGGED} edit"})
    assert edited.status_code == 422, edited.text

    ok_edit = await client.patch(url, headers=headers, json={"body": "still perfect"})
    assert ok_edit.status_code == 200, ok_edit.text


async def test_unfiltered_surfaces_stay_open(client, db_session):
    """Report `detail` goes only to operators reviewing the table, and song
    title/artist are catalog data from search/resolve — neither is filtered.
    (A title from a real catalog entry can contain an edgy word and still be a
    legitimate pick; policing it is reporting's job, not the denylist's.)"""
    reporter = await _seed_user(db_session, "g@example.com", "Gus")
    other = await _seed_user(db_session, "h@example.com", "Hank")
    club, mix_ = await _seed_club_with_mix(db_session, reporter, other, mix_state="closed")

    submission = Submission(
        mix_id=mix_.id,
        user_id=other.id,
        isrc="USABC1234567",
        title="Tame",
        artist="Impalers",
        participation_mode="playing",
    )
    db_session.add(submission)
    await db_session.flush()
    from app.models.note import Note

    note = Note(mix_id=mix_.id, submission_id=submission.id, author_id=other.id, body="nice pick")
    db_session.add(note)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/reports",
        headers=_auth_header(reporter.id),
        json={
            "club_id": str(club.id),
            "content_type": "note",
            "content_id": str(note.id),
            "reason": "other",
            "detail": f"this {_FLAGGED} keeps doing it",
        },
    )
    assert resp.status_code == 201, resp.text
