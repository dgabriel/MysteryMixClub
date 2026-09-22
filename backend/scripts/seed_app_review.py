"""Create the App Store reviewer account and three demo clubs (MysteryMixClub-q5mc
follow-up; App Store readiness P0.5).

Apple's reviewer needs a stable, populated account they can sign into without
inbox access, an invitation, or help from us -- and needs to see the app's core
lifecycle states without hunting for them. This builds exactly that:

  * one reviewer account, password auth (email + password, no magic link)
  * three clubs, each anchored on one mix state:
      1. COMPLETED    -- several submissions, votes, notes, a revealed result
      2. OPEN VOTING  -- synthetic submissions in; the reviewer's own vote is
                         the one thing left outstanding, so there's something
                         to actually DO when they open the club
      3. OPEN SUBMISSION -- left almost empty so the reviewer can add, edit,
                         and remove their own submission freely

Deliberately talks to the PRODUCTION API the same way a real member's browser
does -- POST /auth/register, POST /clubs, POST /mixes/:id/submissions, and so
on -- rather than touching the database directly. That means this needs no
prod SSH, no prod database credentials, and no admin token held by whoever
runs it (never ad hoc; see docs/git-hygiene.md's "no prod SSH" rule). The
*only* privileged step anywhere in this flow is minting one platform invite,
and that's a one-click action from the existing Admin screen (POST
/admin/invites) -- do that first, signed in as a platform admin, and pass the
resulting token in with --invite-token. Everything after that runs as an
ordinary organizer/member would: the reviewer account self-registers with
that invite, then generates its own (multi-use, 48h) club-invite links to
bring the synthetic members in, exactly like any real organizer would.

Idempotent by design, since this is meant to be re-run rather than run once
and forgotten: every account tries to log in before it tries to register,
every club is matched by name before it's created, and every mix/submission/
vote step checks current state before acting. Re-running after a partial
failure (a flaky search, a dropped connection) picks up where it left off
rather than duplicating anything or erroring on "already exists".

Usage (see --help for the rest):

    python -m scripts.seed_app_review \\
        --api-base-url https://api.mysterymixclub.com \\
        --invite-token <token from POST /admin/invites>

Prints the reviewer's email and password at the end, ready to paste into App
Store Connect's Review Notes -- the one place a plaintext password for this
account is supposed to end up.

Exit status: 0 on success, 1 if any step fails outright (a step that can be
safely retried leaves the reviewer account and any clubs already created
intact -- rerun the same command).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

_DEFAULT_REVIEWER_EMAIL = "appreview@dawngabriel.com"
_MEMBER_DOMAIN = "dawngabriel.com"
_PASSWORD_LENGTH = 20
# Not a secret in the "protects something valuable" sense -- see
# _derive_password's docstring for why that's an acceptable tradeoff here.
# Fixed so the same email always derives the same password, run to run,
# machine to machine, which is the entire point.
_PASSWORD_PEPPER = b"MysteryMixClub-app-review-seed-v1"
_REQUEST_TIMEOUT = 20.0

# A small pool of well-known, easy-to-find songs (real Deezer search hits,
# so real ISRCs and real cover art come back) -- enough variety that four
# clubs' worth of submissions don't all collide on the same track. Picked for
# being unambiguous single-result searches, not for taste.
_SONG_POOL = [
    "Here Comes the Sun The Beatles",
    "Dancing Queen ABBA",
    "Superstition Stevie Wonder",
    "Dreams Fleetwood Mac",
    "Ain't No Mountain High Enough Marvin Gaye",
    "Good Vibrations The Beach Boys",
    "Ain't Nobody Chaka Khan",
    "September Earth Wind and Fire",
    "Bizarre Love Triangle New Order",
    "Return of the Mack Mark Morrison",
]

# How many synthetic members join each club, on top of the reviewer.
CLUB_1_MEMBERS = 3  # + the reviewer = 4 playing submitters
CLUB_2_MEMBERS = 2  # + the reviewer = 3 playing submitters


def _derive_password(email: str) -> str:
    """A password unique to `email`, but the SAME one every time this script
    is run -- the point of "idempotent by design": a rerun's login attempt
    has to be able to reproduce whatever password was used to register the
    account originally, and there is no way to recover or reset that
    password without knowing it (no admin bypass here, by design -- see the
    module docstring). A random one, regenerated per run, made every rerun
    for a synthetic member fail login and then fail registration with a 409
    (a real bug this review caught).

    Fine for these accounts specifically: `--invite-token`-gated synthetic
    demo members and a reviewer account whose password is handed to Apple in
    plaintext anyway (see `main`'s own printed output) hold no data more
    sensitive than a handful of seeded playlists. `--reviewer-password` is
    still there for anyone who wants a stronger, unpredictable one instead --
    just pass the identical value on every rerun, the same requirement this
    derivation exists to remove for everyone else."""
    digest = hmac.new(_PASSWORD_PEPPER, email.strip().lower().encode(), hashlib.sha256).hexdigest()
    return digest[:_PASSWORD_LENGTH]


class ApiError(RuntimeError):
    def __init__(self, response: httpx.Response) -> None:
        detail: Any
        try:
            detail = response.json().get("detail")
        except Exception:  # noqa: BLE001 -- best-effort error surface only
            detail = response.text[:300]
        super().__init__(
            f"{response.request.method} {response.request.url} -> {response.status_code}: {detail}"
        )
        self.response = response
        self.status_code = response.status_code


@dataclass
class Account:
    """One signed-in identity against the live API -- its own cookie jar and
    access token, so several accounts never cross streams in the same run."""

    email: str
    password: str
    display_name: str
    client: httpx.Client
    access_token: str = ""
    _user_id: str = ""

    def whoami(self) -> str:
        """This account's own user id, fetched once and cached -- lets club
        matching (see `_find_club_by_name`) confirm a same-named club is
        really one this account organizes, not an unrelated collision."""
        if not self._user_id:
            self._user_id = self.get("/users/me")["id"]
        return self._user_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        resp = self.client.request(method, path, headers=self._headers(), **kwargs)
        return resp

    def get(self, path: str, **kwargs: Any) -> Any:
        resp = self.request("GET", path, **kwargs)
        if resp.status_code >= 400:
            raise ApiError(resp)
        return resp.json()

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        resp = self.request("POST", path, json=json)
        if resp.status_code >= 400:
            raise ApiError(resp)
        return resp.json() if resp.content else None

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        resp = self.request("PATCH", path, json=json)
        if resp.status_code >= 400:
            raise ApiError(resp)
        return resp.json()

    def try_login(self) -> bool:
        resp = self.request(
            "POST", "/auth/login", json={"email": self.email, "password": self.password}
        )
        if resp.status_code == 200:
            self.access_token = resp.json()["access_token"]
            return True
        if resp.status_code in (401,):
            return False
        raise ApiError(resp)

    def register(self, invite_token: str) -> None:
        body = self.post(
            "/auth/register",
            json={"email": self.email, "password": self.password, "invite_token": invite_token},
        )
        self.access_token = body["access_token"]

    def ensure_signed_in(self, invite_token: str) -> None:
        """Log in if the account already exists (a rerun), else register it
        with `invite_token` -- a platform invite for the reviewer, a club
        invite for a synthetic member."""
        if self.try_login():
            print(f"  {self.email}: already exists, logged in")
            return
        self.register(invite_token)
        print(f"  {self.email}: registered")

    def ensure_onboarded(self) -> None:
        """Set a real display name and accept ToS, same as a real first
        login (Help's own description of it) -- idempotent, PATCH /me is
        happy to be called again with the same values."""
        self.patch("/users/me", json={"display_name": self.display_name, "accept_terms": True})


@dataclass
class ClubBuild:
    """One club under construction: the club row, its first mix, and the
    member accounts in it (reviewer first)."""

    id: str
    mix_id: str
    name: str
    members: list[Account] = field(default_factory=list)


def _find_club_by_name(reviewer: Account, name: str) -> dict[str, Any] | None:
    # organizer_id check guards against an unrelated pre-existing club that
    # happens to share one of these names -- unlikely given how specific they
    # are, but cheap to rule out entirely rather than just hope.
    reviewer_id = reviewer.whoami()
    for club in reviewer.get("/clubs"):
        if club["name"] == name and club.get("organizer_id") == reviewer_id:
            return club
    return None


def ensure_club(
    reviewer: Account, name: str, description: str, total_rounds: int
) -> dict[str, Any]:
    existing = _find_club_by_name(reviewer, name)
    if existing is not None:
        print(f"  club {name!r}: already exists")
        return existing
    club = reviewer.post(
        "/clubs",
        json={
            "name": name,
            "description": description,
            "total_rounds": total_rounds,
            # The max the API allows (168h = 7 days) on both phases, so
            # nothing in any of these clubs auto-advances or expires purely
            # from elapsed time during a review cycle.
            "submission_window_hours": 168,
            "voting_window_hours": 168,
        },
    )
    print(f"  club {name!r}: created ({club['id']})")
    return club


def ensure_member(
    reviewer: Account,
    club_id: str,
    client_factory: Callable[[], httpx.Client],
    email: str,
    display_name: str,
) -> Account:
    """A synthetic member of `club_id` -- self-registers via a fresh club
    invite if it doesn't already exist. Club invites are multi-use and
    48h-lived, so minting a new one per member (or reusing one across several
    members in the same run) is both fine and simple."""
    account = Account(
        email=email,
        password=_derive_password(email),
        display_name=display_name,
        client=client_factory(),
    )
    if account.try_login():
        print(f"    {email}: already a member, logged in")
        return account
    invite = reviewer.post(f"/clubs/{club_id}/invites")
    account.register(invite["token"])
    account.ensure_onboarded()
    print(f"    {email}: registered and joined")
    return account


def ensure_mix_open_for_submission(organizer: Account, club_id: str, theme: str) -> dict[str, Any]:
    mixes = organizer.get(f"/clubs/{club_id}/mixes")
    mix = next(m for m in mixes if m["round_number"] == 1)
    if mix["state"] == "pending":
        mix = organizer.patch(
            f"/mixes/{mix['id']}", json={"theme": theme, "state": "open_submission"}
        )
        print(f"    mix 1: opened for submission ({theme!r})")
    return mix


def ensure_mix_open_for_voting(organizer: Account, mix_id: str) -> dict[str, Any]:
    mix = organizer.get(f"/mixes/{mix_id}")
    if mix["state"] == "open_submission":
        mix = organizer.patch(f"/mixes/{mix_id}", json={"state": "open_voting"})
        print(f"    mix 1: opened for voting (state now {mix['state']!r})")
    return mix


_song_index = 0


def _next_song(session: Account) -> dict[str, Any] | None:
    """The next pool entry with a usable ISRC, trying each in turn (a
    transient Deezer hiccup or a since-delisted track shouldn't sink the
    whole run) -- None if the whole pool is exhausted."""
    global _song_index
    for _ in range(len(_SONG_POOL)):
        query = _SONG_POOL[_song_index % len(_SONG_POOL)]
        _song_index += 1
        try:
            result = session.get("/songs/search", params={"q": query})
        except ApiError as exc:
            print(f"    search {query!r} failed: {exc}", file=sys.stderr)
            continue
        for track in result["results"]:
            if track.get("isrc"):
                return track
    return None


def ensure_submission(session: Account, mix_id: str) -> bool:
    """True if this member now has a submission in `mix_id` (already had one,
    or just added one). False only if the song pool is exhausted."""
    mine = session.get(f"/mixes/{mix_id}/submissions/mine")
    if mine:
        return True
    track = _next_song(session)
    if track is None:
        print(f"    {session.email}: no song found to submit (pool exhausted)", file=sys.stderr)
        return False
    session.post(
        f"/mixes/{mix_id}/submissions",
        json={
            "isrc": track["isrc"],
            "title": track["title"],
            "artist": track["artist"] or "Unknown Artist",
            "album": track.get("album"),
            "album_art_url": track.get("thumbnail_url"),
            "participation_mode": "playing",
        },
    )
    print(f"    {session.email}: submitted {track['title']!r}")
    return True


def cast_vote_for_others(session: Account, mix_id: str, max_votes: int) -> None:
    """Vote for up to `max_votes` OTHER members' submissions -- a no-op if
    this member already voted (Help: 'is voting anonymous? ... no self-votes'
    is the one hard rule; everything else is fair game)."""
    if session.get(f"/mixes/{mix_id}/votes/mine")["submission_ids"]:
        return
    playlist = session.get(f"/mixes/{mix_id}/playlist")
    candidates = [e["submission_id"] for e in playlist["entries"] if not e["is_own"]]
    picks = candidates[:max_votes]
    if not picks:
        return
    session.post(f"/mixes/{mix_id}/votes", json={"submission_ids": picks})
    print(f"    {session.email}: voted for {len(picks)} song(s)")


def leave_a_note(session: Account, mix_id: str) -> None:
    playlist = session.get(f"/mixes/{mix_id}/playlist")
    others = [e for e in playlist["entries"] if not e["is_own"]]
    if not others:
        return
    submission_id = others[0]["submission_id"]
    try:
        session.post(
            f"/submissions/{submission_id}/notes", json={"body": "this one's a great pick!"}
        )
    except ApiError as exc:
        if exc.status_code != 409:  # already left a note on this submission -- fine
            raise


def build_club_completed(
    reviewer: Account, client_factory: Callable[[], httpx.Client]
) -> ClubBuild:
    name = "App Review Club 1"
    print(f"\n== {name} (target: COMPLETED) ==")
    club = ensure_club(
        reviewer,
        name,
        "A completed mystery mix, for App Store review -- results, notes, and provider links.",
        total_rounds=1,
    )
    members = [reviewer] + [
        ensure_member(
            reviewer,
            club["id"],
            client_factory,
            f"mmc-review-club1-{n}@{_MEMBER_DOMAIN}",
            f"Review Member {n}",
        )
        for n in range(1, CLUB_1_MEMBERS + 1)
    ]
    mix = ensure_mix_open_for_submission(reviewer, club["id"], "Songs for a Long Drive")
    for m in members:
        ensure_submission(m, mix["id"])
    mix = ensure_mix_open_for_voting(reviewer, mix["id"])
    if mix["state"] == "open_voting":
        # The note has to land BEFORE the last vote below: casting every
        # playing member's vote meets quorum and auto-closes the mix on the
        # spot, and a playing member can't leave a note once it's closed
        # (only a vibing one can, per _notes_open) -- so note first, vote last.
        leave_a_note(members[1], mix["id"])
        for m in members:
            cast_vote_for_others(m, mix["id"], max_votes=2)
        final = reviewer.get(f"/mixes/{mix['id']}")
        print(f"    mix 1 is now {final['state']!r} (quorum auto-closes once everyone's voted)")
    return ClubBuild(id=club["id"], mix_id=mix["id"], name=name, members=members)


def build_club_open_voting(
    reviewer: Account, client_factory: Callable[[], httpx.Client]
) -> ClubBuild:
    name = "App Review Club 2"
    print(f"\n== {name} (target: OPEN VOTING) ==")
    club = ensure_club(
        reviewer,
        name,
        "A mystery mix open for voting, for App Store review -- the reviewer's own vote is "
        "the one thing left to do here.",
        total_rounds=3,
    )
    members = [reviewer] + [
        ensure_member(
            reviewer,
            club["id"],
            client_factory,
            f"mmc-review-club2-{n}@{_MEMBER_DOMAIN}",
            f"Review Member {n}",
        )
        for n in range(1, CLUB_2_MEMBERS + 1)
    ]
    mix = ensure_mix_open_for_submission(reviewer, club["id"], "One-Hit Wonders")
    for m in members:
        ensure_submission(m, mix["id"])
    mix = ensure_mix_open_for_voting(reviewer, mix["id"])
    # Only the synthetic members vote -- the reviewer's own vote is left
    # outstanding on purpose, so there's something to do when they check the
    # build. Casting it here would immediately close the mix (quorum) and
    # defeat the point.
    for m in members[1:]:
        cast_vote_for_others(m, mix["id"], max_votes=2)
    return ClubBuild(id=club["id"], mix_id=mix["id"], name=name, members=members)


def build_club_open_submission(reviewer: Account) -> ClubBuild:
    name = "App Review Club 3"
    print(f"\n== {name} (target: OPEN SUBMISSION) ==")
    club = ensure_club(
        reviewer,
        name,
        "A mystery mix open for submissions, for App Store review -- the reviewer can add, "
        "edit, and remove their own submission here.",
        total_rounds=3,
    )
    mix = ensure_mix_open_for_submission(reviewer, club["id"], "Songs About the Sea")
    # Left otherwise empty on purpose (no synthetic submissions) so the
    # reviewer's add/edit/remove cycle only ever touches their own row.
    return ClubBuild(id=club["id"], mix_id=mix["id"], name=name, members=[reviewer])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--api-base-url",
        required=True,
        help="e.g. https://api.mysterymixclub.com/api/v1 -- point this at "
        "whichever environment the app under review actually talks to.",
    )
    parser.add_argument(
        "--invite-token",
        required=True,
        help="A platform invite token from POST /admin/invites (Admin screen, "
        "signed in as a platform admin). Only used if the reviewer "
        "account doesn't already exist.",
    )
    parser.add_argument("--reviewer-email", default=_DEFAULT_REVIEWER_EMAIL)
    parser.add_argument(
        "--reviewer-password",
        default=None,
        help="Omit to derive a stable password from --reviewer-email (same one every "
        "run, so a rerun can still log in). Pass one explicitly for a stronger, "
        "unpredictable password instead -- but then pass that SAME value again on "
        "every rerun, or the next run's login attempt will fail.",
    )
    args = parser.parse_args()

    def client_factory() -> httpx.Client:
        return httpx.Client(base_url=args.api_base_url, timeout=_REQUEST_TIMEOUT)

    reviewer_password = args.reviewer_password or _derive_password(args.reviewer_email)
    reviewer = Account(
        email=args.reviewer_email,
        password=reviewer_password,
        display_name="App Reviewer",
        client=client_factory(),
    )

    print(f"== reviewer account ({reviewer.email}) ==")
    try:
        reviewer.ensure_signed_in(args.invite_token)
        reviewer.ensure_onboarded()

        club1 = build_club_completed(reviewer, client_factory)
        club2 = build_club_open_voting(reviewer, client_factory)
        club3 = build_club_open_submission(reviewer)
    except Exception as exc:  # noqa: BLE001 -- top-level CLI entrypoint: ANY failure
        # (an API error, a dropped connection, an unexpected response shape)
        # should end in the documented "safe to rerun" message, not a raw
        # traceback -- catching only ApiError here left everything else
        # (a timeout, a StopIteration from an unexpectedly empty mix list)
        # exiting with an unhandled stack trace instead.
        print(f"\nFAILED: {exc}", file=sys.stderr)
        print(
            "Safe to rerun the same command -- every step checks current state first.",
            file=sys.stderr,
        )
        return 1

    print("\n" + "=" * 72)
    print("Done. For App Store Connect's Review Notes:")
    print("=" * 72)
    # Deliberately prints the plaintext password: it's meant to be copied
    # straight into App Store Connect's Review Notes field, the one place
    # this account's password is supposed to end up (see the module
    # docstring). Not a leak -- the destination is the whole point.
    print(  # lgtm[py/clear-text-logging-sensitive-data]
        f"""
REVIEW ACCOUNT
Email: {reviewer.email}
Password: {reviewer_password if not args.reviewer_password else "(the one you supplied)"}

SUGGESTED REVIEW FLOW
1. Sign in with the review credentials above.
2. Open "{club1.name}" -- a completed mystery mix: results, notes, and
   provider links.
3. Open "{club2.name}" -- open for voting. Cast a vote to see the flow
   through to a result.
4. Open "{club3.name}" -- open for submission. Add, edit, and remove a
   submission.
"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
