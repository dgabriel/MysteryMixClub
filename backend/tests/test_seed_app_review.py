"""Exercises scripts/seed_app_review.py against a small fake API, not a real
server -- the script is meant to run against production later
(MysteryMixClub-q5mc follow-up), so this is the only rehearsal it gets before
then. The fake backend (`_FakeApi`) implements just enough of the real
invariants (invite gating, forward-only mix states, theme-required-to-open,
one-vote-per-member, vote quorum auto-closing a mix, note-requires-open-voting)
to catch a script bug that only shows up against those rules -- exactly the
class of bug this test suite caught once already (see
test_completed_club_leaves_a_note_before_the_closing_vote below, which pins
the fix for a note-after-auto-close ordering bug found while writing this).

MissingGreenlet-style trap avoided the mundane way here (no ORM): the fake
API is a plain in-memory dict store, so there's nothing to expire.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from scripts import seed_app_review as sar

_INVITE_TOKEN = "platform-invite-token"
# Captured before any test monkeypatches httpx.Client, so the fixtures below
# can build a real client (wired to the fake transport) without recursing
# into whatever main() has had httpx.Client swapped out for.
_REAL_CLIENT = httpx.Client


class _FakeApi:
    """A tiny in-memory stand-in for the real backend, covering only the
    endpoints seed_app_review.py calls, with the same shape of rules that
    matter to its logic (not a full reimplementation of the real routes)."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}  # email -> {password, token, display_name, id}
        self.tokens: dict[str, str] = {}  # access_token -> email
        self.club_invites: dict[str, str] = {}  # token -> club_id
        self.clubs: dict[str, dict[str, Any]] = {}
        self.mixes: dict[str, dict[str, Any]] = {}  # mix_id -> {..., club_id, mix_number}
        self.submissions: dict[str, list[dict[str, Any]]] = {}  # mix_id -> [submission]
        self.votes: dict[str, dict[str, list[str]]] = {}  # mix_id -> {user_id: [submission_id]}
        self.notes: dict[str, set[tuple[str, str]]] = {}  # mix_id -> {(author_id, submission_id)}
        self.members: dict[str, set[str]] = {}  # club_id -> {user_id}
        self.blocks: dict[str, set[str]] = {}  # blocker user_id -> {blocked user_id}

    # -- helpers ------------------------------------------------------------
    def _user_for(self, request: httpx.Request) -> dict[str, Any]:
        auth = request.headers.get("authorization", "")
        token = auth.removeprefix("Bearer ")
        email = self.tokens.get(token)
        assert email is not None, "unauthenticated request in test"
        return self.users[email]

    def _issue_token(self, email: str) -> str:
        token = f"tok-{uuid.uuid4()}"
        self.tokens[token] = email
        return token

    def _add_pending_mixes(self, club_id: str, start: int, end: int) -> None:
        for n in range(start, end + 1):
            mix_id = f"mix-{uuid.uuid4()}"
            self.mixes[mix_id] = {
                "id": mix_id,
                "club_id": club_id,
                "mix_number": n,
                "theme": None,
                "state": "pending",
            }
            self.submissions[mix_id] = []
            self.votes[mix_id] = {}
            self.notes[mix_id] = set()

    # -- request dispatch -----------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body = {} if not request.content else json.loads(request.content)

        if method == "POST" and path == "/auth/login":
            user = self.users.get(body["email"])
            if user is None or user["password"] != body["password"]:
                return httpx.Response(401, json={"detail": "invalid credentials"})
            return httpx.Response(200, json={"access_token": self._issue_token(body["email"])})

        if method == "POST" and path == "/auth/register":
            email = body["email"]
            if email in self.users:
                return httpx.Response(409, json={"detail": "account exists"})
            valid_invite = (
                body["invite_token"] == _INVITE_TOKEN or body["invite_token"] in self.club_invites
            )
            if not valid_invite:
                return httpx.Response(403, json={"detail": "invite required"})
            self.users[email] = {
                "id": f"user-{uuid.uuid4()}",
                "password": body["password"],
                "display_name": email,
                "email_notifications": True,
            }
            if body["invite_token"] in self.club_invites:
                club_id = self.club_invites[body["invite_token"]]
                self.members[club_id].add(self.users[email]["id"])
            return httpx.Response(201, json={"access_token": self._issue_token(email)})

        if method == "GET" and path == "/users/me":
            user = self._user_for(request)
            return httpx.Response(200, json={"id": user["id"]})

        if method == "PATCH" and path == "/users/me":
            user = self._user_for(request)
            if "display_name" in body:
                user["display_name"] = body["display_name"]
            return httpx.Response(200, json={"ok": True})

        if method == "GET" and path == "/clubs":
            # Scoped by membership like the real list_clubs, so a rebuilt
            # club's rejoin path (ensure_member) is actually exercised. A club
            # flagged `visible_to_all` is listed regardless: that lets
            # test_does_not_reuse_a_same_named_club_organized_by_someone_else
            # exercise the SCRIPT's own organizer_id guard (_find_club_by_name)
            # in isolation, rather than relying on server-side scoping to hide
            # a collision the guard exists to catch either way.
            user = self._user_for(request)
            listed = [
                c
                for c in self.clubs.values()
                if c.get("visible_to_all") or user["id"] in self.members.get(c["id"], set())
            ]
            return httpx.Response(200, json=listed)

        if method == "POST" and path == "/clubs":
            user = self._user_for(request)
            club_id = f"club-{uuid.uuid4()}"
            club = {"id": club_id, "name": body["name"], "organizer_id": user["id"]}
            self.clubs[club_id] = club
            self.members[club_id] = {user["id"]}
            self._add_pending_mixes(club_id, start=1, end=body.get("total_rounds", 6))
            return httpx.Response(201, json=club)

        if method == "POST" and path.startswith("/clubs/") and path.endswith("/invites"):
            club_id = path.split("/")[2]
            token = f"club-invite-{uuid.uuid4()}"
            self.club_invites[token] = club_id
            return httpx.Response(201, json={"token": token})

        if method == "DELETE" and path.startswith("/clubs/") and path.count("/") == 2:
            club_id = path.split("/")[2]
            user = self._user_for(request)
            if self.clubs[club_id]["organizer_id"] != user["id"]:
                return httpx.Response(403, json={"detail": "organizer only"})
            for mix_id in [mid for mid, m in self.mixes.items() if m["club_id"] == club_id]:
                del self.mixes[mix_id], self.submissions[mix_id], self.votes[mix_id]
                del self.notes[mix_id]
            del self.clubs[club_id], self.members[club_id]
            return httpx.Response(204)

        if method == "POST" and path.startswith("/invites/") and path.endswith("/accept"):
            club_id = self.club_invites[path.split("/")[2]]
            self.members[club_id].add(self._user_for(request)["id"])
            return httpx.Response(200, json=self.clubs[club_id])

        if method == "GET" and path == "/users/me/blocks":
            user = self._user_for(request)
            by_id = {u["id"]: u for u in self.users.values()}
            return httpx.Response(
                200,
                json=[
                    {"user_id": b, "display_name": by_id[b]["display_name"]}
                    for b in sorted(self.blocks.get(user["id"], set()))
                ],
            )

        if method == "DELETE" and path.startswith("/users/me/blocks/"):
            user = self._user_for(request)
            self.blocks.get(user["id"], set()).discard(path.split("/")[-1])
            return httpx.Response(204)

        if method == "PATCH" and path.startswith("/clubs/") and path.count("/") == 2:
            # Mirrors the real PATCH /clubs/:id's total_rounds growth
            # (_reconcile_mixes): appends pending mixes numbered above
            # whatever the highest existing mix_number is. Shrinking isn't
            # modeled -- the seeding script only ever grows this club.
            club_id = path.split("/")[2]
            new_total = body.get("total_rounds")
            if new_total is not None:
                current_max = max(
                    (m["mix_number"] for m in self.mixes.values() if m["club_id"] == club_id),
                    default=0,
                )
                self._add_pending_mixes(club_id, start=current_max + 1, end=new_total)
            return httpx.Response(200, json=self.clubs[club_id])

        if method == "GET" and path.startswith("/clubs/") and path.endswith("/mixes"):
            club_id = path.split("/")[2]
            mixes = [m for m in self.mixes.values() if m["club_id"] == club_id]
            return httpx.Response(200, json=mixes)

        if path.startswith("/mixes/"):
            return self._handle_mix(request, method, path, body)

        if method == "GET" and path == "/songs/search":
            q = request.url.params["q"]
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "1",
                            "title": q.split(" ")[0] + " (a song)",
                            "artist": "Someone",
                            "album": "An Album",
                            "thumbnail_url": "https://example.com/art.jpg",
                            "isrc": f"ISRC{abs(hash(q)) % 10**9:09d}",
                        }
                    ],
                    "too_many_results": False,
                },
            )

        if method == "GET" and path.startswith("/submissions/") and path.endswith("/notes"):
            # Closed-mix reads only (all the script does): everyone's notes,
            # minus authors the caller blocked -- the real list_notes rule.
            submission_id = path.split("/")[2]
            user = self._user_for(request)
            blocked = self.blocks.get(user["id"], set())
            notes = [
                {"author_id": author}
                for subs in self.notes.values()
                for author, sid in subs
                if sid == submission_id and author not in blocked
            ]
            return httpx.Response(200, json=notes)

        if method == "POST" and path.startswith("/submissions/") and path.endswith("/notes"):
            submission_id = path.split("/")[2]
            user = self._user_for(request)
            mix_id = next(
                mid
                for mid, subs in self.submissions.items()
                if any(s["id"] == submission_id for s in subs)
            )
            if self.mixes[mix_id]["state"] != "open_voting":
                return httpx.Response(409, json={"detail": "notes are not open"})
            key = (user["id"], submission_id)
            if key in self.notes[mix_id]:
                return httpx.Response(409, json={"detail": "already noted"})
            self.notes[mix_id].add(key)
            return httpx.Response(201, json={"id": f"note-{uuid.uuid4()}"})

        raise AssertionError(f"unhandled request: {method} {path}")

    def _handle_mix(
        self, request: httpx.Request, method: str, path: str, body: dict
    ) -> httpx.Response:
        parts = path.split("/")
        mix_id = parts[2]
        mix = self.mixes[mix_id]

        if method == "PATCH" and len(parts) == 3:
            if "theme" in body:
                mix["theme"] = body["theme"]
            new_state = body.get("state")
            if new_state:
                order = ["pending", "open_submission", "open_voting", "closed"]
                if order.index(new_state) != order.index(mix["state"]) + 1:
                    return httpx.Response(409, json={"detail": "invalid transition"})
                if new_state == "open_submission" and not mix["theme"]:
                    return httpx.Response(409, json={"detail": "theme required"})
                mix["state"] = new_state
            return httpx.Response(200, json=mix)

        if method == "GET" and len(parts) == 3:
            return httpx.Response(200, json=mix)

        if method == "POST" and path.endswith("/submissions"):
            user = self._user_for(request)
            sub = {
                "id": f"sub-{uuid.uuid4()}",
                "user_id": user["id"],
                "isrc": body["isrc"],
                "title": body["title"],
                "artist": body["artist"],
                "album": body.get("album"),
                "album_art_url": body.get("album_art_url"),
                "participation_mode": body.get("participation_mode", "playing"),
            }
            self.submissions[mix_id].append(sub)
            return httpx.Response(201, json=sub)

        if method == "GET" and path.endswith("/submissions/mine"):
            user = self._user_for(request)
            return httpx.Response(
                200, json=[s for s in self.submissions[mix_id] if s["user_id"] == user["id"]]
            )

        if method == "GET" and path.endswith("/playlist"):
            if mix["state"] == "open_submission":
                return httpx.Response(409, json={"detail": "not open for voting yet"})
            user = self._user_for(request)
            entries = [
                {
                    "submission_id": s["id"],
                    "isrc": s["isrc"],
                    "title": s["title"],
                    "artist": s["artist"],
                    "album": s["album"],
                    "album_art_url": s["album_art_url"],
                    "is_own": s["user_id"] == user["id"],
                }
                for s in self.submissions[mix_id]
            ]
            return httpx.Response(200, json={"entries": entries})

        if method == "POST" and path.endswith("/votes"):
            user = self._user_for(request)
            self.votes[mix_id][user["id"]] = body["submission_ids"]
            playing_ids = {
                s["user_id"]
                for s in self.submissions[mix_id]
                if s["participation_mode"] == "playing"
            }
            if playing_ids and playing_ids.issubset(self.votes[mix_id].keys()):
                mix["state"] = "closed"
            return httpx.Response(
                200,
                json={
                    "round_id": mix_id,
                    "submission_ids": body["submission_ids"],
                    "count": len(body["submission_ids"]),
                    "votes_per_player": 3,
                },
            )

        if method == "GET" and path.endswith("/votes/mine"):
            user = self._user_for(request)
            return httpx.Response(
                200,
                json={
                    "round_id": mix_id,
                    "submission_ids": self.votes[mix_id].get(user["id"], []),
                    "count": len(self.votes[mix_id].get(user["id"], [])),
                    "votes_per_player": 3,
                },
            )

        raise AssertionError(f"unhandled mix request: {method} {path}")


@pytest.fixture
def fake_api(monkeypatch):
    api = _FakeApi()

    def client_factory() -> httpx.Client:
        transport = httpx.MockTransport(api.handle)
        return _REAL_CLIENT(base_url="https://fake.example.com", transport=transport)

    return api, client_factory


def _run(monkeypatch, client_factory, **extra_args) -> int:
    argv = [
        "seed_app_review.py",
        "--api-base-url",
        "https://fake.example.com/api/v1",
        "--invite-token",
        _INVITE_TOKEN,
    ]
    for key, value in extra_args.items():
        argv += [f"--{key.replace('_', '-')}", value]
    monkeypatch.setattr("sys.argv", argv)

    # main() builds its own client_factory closure from args; swap httpx.Client
    # itself so every client it constructs goes through the fake transport,
    # regardless of how it's built inside main().
    real_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs.pop("transport", None)
        return client_factory()

    monkeypatch.setattr(httpx, "Client", patched_client)
    try:
        return sar.main()
    finally:
        monkeypatch.setattr(httpx, "Client", real_client)


def test_full_run_reaches_all_three_target_states(monkeypatch, fake_api, capsys):
    api, client_factory = fake_api

    exit_code = _run(monkeypatch, client_factory)

    assert exit_code == 0
    clubs = {c["name"]: c for c in api.clubs.values()}
    assert set(clubs) == {"App Review Club 1", "App Review Club 2", "App Review Club 3"}

    def mix1(club_id: str) -> dict:
        return next(
            m for m in api.mixes.values() if m["club_id"] == club_id and m["mix_number"] == 1
        )

    club1_mix = mix1(clubs["App Review Club 1"]["id"])
    club2_mix = mix1(clubs["App Review Club 2"]["id"])
    club3_mix = mix1(clubs["App Review Club 3"]["id"])

    assert club1_mix["state"] == "closed"
    assert len(api.submissions[club1_mix["id"]]) == 4  # reviewer + 3 synthetic
    assert len(api.notes[club1_mix["id"]]) == sar.CLUB_1_MEMBERS * sar.CLUB_1_MEMBERS

    assert club2_mix["state"] == "open_voting"
    assert len(api.submissions[club2_mix["id"]]) == 3  # reviewer + 2 synthetic
    reviewer = api.users["appreview@dawngabriel.com"]
    assert api.votes[club2_mix["id"]].get(reviewer["id"]) in (None, [])  # reviewer hasn't voted

    assert club3_mix["state"] == "open_submission"
    assert api.submissions[club3_mix["id"]] == []

    out = capsys.readouterr().out
    assert "REVIEW ACCOUNT" in out
    assert "appreview@dawngabriel.com" in out


def test_completed_club_leaves_a_note_before_the_closing_vote(monkeypatch, fake_api):
    """Pins the fix for a real bug found while writing this script: voting
    with every playing member auto-closes the mix (quorum), and a playing
    member can't leave a note on a closed mix -- so the note has to happen
    before the last vote, not after. If that ordering regresses, the run
    fails outright instead of silently skipping the note."""
    api, client_factory = fake_api

    exit_code = _run(monkeypatch, client_factory)

    assert exit_code == 0
    club1 = next(c for c in api.clubs.values() if c["name"] == "App Review Club 1")
    mix = next(
        m for m in api.mixes.values() if m["club_id"] == club1["id"] and m["mix_number"] == 1
    )
    assert mix["state"] == "closed"
    # Every synthetic member notes every song but their own: 3 authors x 3.
    assert len(api.notes[mix["id"]]) == sar.CLUB_1_MEMBERS * sar.CLUB_1_MEMBERS
    noted_songs = {sid for _, sid in api.notes[mix["id"]]}
    assert len(noted_songs) >= sar.CLUB_1_MIN_NOTED_SONGS


def _club_1(api: _FakeApi) -> tuple[dict[str, Any], dict[str, Any]]:
    club = next(c for c in api.clubs.values() if c["name"] == "App Review Club 1")
    mix = next(m for m in api.mixes.values() if m["club_id"] == club["id"] and m["mix_number"] == 1)
    return club, mix


def test_rebuilds_a_closed_club_1_with_too_few_notes(monkeypatch, fake_api):
    """MysteryMixClub-4vii.46: an environment seeded before notes covered
    every song has a closed Club 1 with a single note. Closed mixes take no
    new notes, so the rerun deletes and rebuilds it -- and the existing
    synthetic accounts must rejoin the new club, not just log in."""
    api, client_factory = fake_api
    assert _run(monkeypatch, client_factory) == 0
    old_club, old_mix = _club_1(api)
    keep = next(iter(api.notes[old_mix["id"]]))
    api.notes[old_mix["id"]] = {keep}

    assert _run(monkeypatch, client_factory) == 0

    new_club, new_mix = _club_1(api)
    assert new_club["id"] != old_club["id"]
    assert old_club["id"] not in api.clubs
    assert new_mix["state"] == "closed"
    assert len({sid for _, sid in api.notes[new_mix["id"]]}) >= sar.CLUB_1_MIN_NOTED_SONGS
    assert len(api.members[new_club["id"]]) == sar.CLUB_1_MEMBERS + 1


def test_rerun_keeps_a_club_1_that_already_has_enough_notes(monkeypatch, fake_api):
    api, client_factory = fake_api
    assert _run(monkeypatch, client_factory) == 0
    first_club, _ = _club_1(api)

    assert _run(monkeypatch, client_factory) == 0

    assert _club_1(api)[0]["id"] == first_club["id"]


def test_rerun_clears_the_reviewers_blocks(monkeypatch, fake_api):
    """A block left by a previous review pass hides that member's notes from
    the reviewer, leaving nothing to report -- the rerun must undo it without
    mistaking the hidden notes for a Club 1 that needs rebuilding."""
    api, client_factory = fake_api
    assert _run(monkeypatch, client_factory) == 0
    club, _ = _club_1(api)
    reviewer_id = api.users["appreview@dawngabriel.com"]["id"]
    member_ids = api.members[club["id"]] - {reviewer_id}
    api.blocks[reviewer_id] = set(member_ids)

    assert _run(monkeypatch, client_factory) == 0

    assert api.blocks[reviewer_id] == set()
    assert _club_1(api)[0]["id"] == club["id"]


def test_rerun_is_idempotent(monkeypatch, fake_api):
    """No password is monkeypatched here on purpose: this has to exercise the
    REAL _derive_password, since the bug this pins (found in review) was
    exactly a rerun using a different password than the one the account was
    registered with -- login failing, then registration 409ing, then the
    whole run aborting. A mock that fixed the password would have hidden it,
    which is exactly what happened the first time this test was written."""
    api, client_factory = fake_api

    first = _run(monkeypatch, client_factory)
    assert first == 0
    user_count, club_count = len(api.users), len(api.clubs)

    second = _run(monkeypatch, client_factory)

    assert second == 0
    assert len(api.users) == user_count
    assert len(api.clubs) == club_count
    club1 = next(c for c in api.clubs.values() if c["name"] == "App Review Club 1")
    mix = next(
        m for m in api.mixes.values() if m["club_id"] == club1["id"] and m["mix_number"] == 1
    )
    # Still closed, same notes -- no duplicate vote/note attempts.
    assert mix["state"] == "closed"
    assert len(api.notes[mix["id"]]) == sar.CLUB_1_MEMBERS * sar.CLUB_1_MEMBERS
    assert len(api.submissions[mix["id"]]) == 4


def test_club_2_opens_a_fresh_mix_after_the_reviewers_vote_closes_the_current_one(
    monkeypatch, fake_api
):
    """Pins MysteryMixClub-4vii.40: Apple's reviewer casting their one
    outstanding vote closes club 2's mix (quorum). A rerun of the script has
    to find a SECOND mix ready for the same voting demo -- not leave the
    club with nothing left to do for a follow-up review pass."""
    api, client_factory = fake_api

    first = _run(monkeypatch, client_factory)
    assert first == 0

    club2 = next(c for c in api.clubs.values() if c["name"] == "App Review Club 2")
    mix1 = next(
        m for m in api.mixes.values() if m["club_id"] == club2["id"] and m["mix_number"] == 1
    )
    assert mix1["state"] == "open_voting"

    # The reviewer casts their outstanding vote directly, the same way
    # Apple's reviewer would from the app -- closing mix 1 via quorum,
    # exactly the live scenario 4vii.40 was filed against.
    reviewer_account = sar.Account(
        email=sar._DEFAULT_REVIEWER_EMAIL,
        password=sar._derive_password(sar._DEFAULT_REVIEWER_EMAIL),
        display_name="App Reviewer",
        client=client_factory(),
    )
    assert reviewer_account.try_login()
    playlist = reviewer_account.get(f"/mixes/{mix1['id']}/playlist")
    candidates = [e["submission_id"] for e in playlist["entries"] if not e["is_own"]]
    reviewer_account.post(f"/mixes/{mix1['id']}/votes", json={"submission_ids": candidates[:2]})
    assert api.mixes[mix1["id"]]["state"] == "closed"

    second = _run(monkeypatch, client_factory)
    assert second == 0

    mix2 = next(
        m for m in api.mixes.values() if m["club_id"] == club2["id"] and m["mix_number"] == 2
    )
    assert mix2["state"] == "open_voting"
    assert len(api.submissions[mix2["id"]]) == 3  # reviewer + 2 synthetic

    reviewer = api.users[sar._DEFAULT_REVIEWER_EMAIL]
    voter_ids = set(api.votes[mix2["id"]].keys())
    assert reviewer["id"] not in voter_ids  # still the one thing left outstanding
    assert len(voter_ids) == 2  # both synthetic members voted

    # No duplicate club and no duplicate synthetic members from the reset.
    assert sum(1 for c in api.clubs.values() if c["name"] == "App Review Club 2") == 1
    club2_members = [
        e for e in api.users if e.startswith("mmc-review-club2-") and e.endswith(sar._MEMBER_DOMAIN)
    ]
    assert len(club2_members) == 2


def test_does_not_reuse_a_same_named_club_organized_by_someone_else(monkeypatch, fake_api):
    api, client_factory = fake_api
    # An unrelated pre-existing club that happens to share a name this script
    # uses -- created by someone other than the reviewer.
    api.users["someone-else@example.com"] = {
        "id": "user-someone-else",
        "password": "irrelevant",
        "display_name": "Someone Else",
    }
    foreign_club_id = "club-foreign"
    api.clubs[foreign_club_id] = {
        "id": foreign_club_id,
        "name": "App Review Club 1",
        "organizer_id": "user-someone-else",
        "visible_to_all": True,
    }

    exit_code = _run(monkeypatch, client_factory)

    assert exit_code == 0
    reviewer = api.users["appreview@dawngabriel.com"]
    mine = [
        c
        for c in api.clubs.values()
        if c["name"] == "App Review Club 1" and c["organizer_id"] == reviewer["id"]
    ]
    # A fresh club of its own, not the foreign one reused.
    assert len(mine) == 1
    assert mine[0]["id"] != foreign_club_id


def test_reviewer_password_argument_is_used_when_supplied(monkeypatch, fake_api):
    api, client_factory = fake_api

    exit_code = _run(monkeypatch, client_factory, reviewer_password="Given-Password-123")

    assert exit_code == 0
    assert api.users["appreview@dawngabriel.com"]["password"] == "Given-Password-123"


def test_a_failed_step_exits_nonzero_without_crashing(monkeypatch, fake_api, capsys):
    api, client_factory = fake_api

    def broken_factory() -> httpx.Client:
        def always_fail(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "boom"})

        return _REAL_CLIENT(
            base_url="https://fake.example.com", transport=httpx.MockTransport(always_fail)
        )

    exit_code = _run(monkeypatch, broken_factory)

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert "rerun" in err.lower()
