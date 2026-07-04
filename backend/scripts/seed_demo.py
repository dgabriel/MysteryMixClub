"""Seed a local demo league for eyeballing the closed-round reveal summary.

Creates (idempotently) a league "Demo Mixtape" owned by a known organizer email
with two CLOSED rounds wired to exercise the league-page winner / most-noted
card summary (MYS-65):

  - Round 1 — a single clear winner (most votes) whose song is *not* the
    most-noted pick, so winner and most-noted differ.
  - Round 2 — a TIE for the winner (two players level on votes) *and* a tie for
    most-noted (two songs level on notes), so both render their plural form.

Plus two trailing pending rounds to fill the slate.

Re-running wipes the prior "Demo Mixtape" league (and its rounds, submissions,
votes, notes, memberships) and rebuilds it; the demo users are reused.

Usage (from backend/, with the venv on PATH and Postgres up):
    python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.league import League
from app.models.league_member import LeagueMember
from app.models.note import Note
from app.models.round import Round
from app.models.spotify_round_playlist import SpotifyRoundPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

# The organizer email is the local user's, so signing in with it (via the
# dev magic-link) lands you on this league as the organizer.
ORGANIZER_EMAIL = "dgabriel@gmail.com"
LEAGUE_NAME = "Demo Mixtape"

NOW = datetime.now(timezone.utc)


async def find_or_create_user(session, email: str, display_name: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name=display_name)
        session.add(user)
        await session.flush()
    elif not user.display_name:
        # An existing-but-not-onboarded account: give it a name so it shows up.
        user.display_name = display_name
    return user


async def wipe_existing_league(session) -> None:
    league_ids = (
        (await session.execute(select(League.id).where(League.name == LEAGUE_NAME))).scalars().all()
    )
    if not league_ids:
        return
    round_ids = (
        (await session.execute(select(Round.id).where(Round.league_id.in_(league_ids))))
        .scalars()
        .all()
    )
    if round_ids:
        await session.execute(delete(Vote).where(Vote.round_id.in_(round_ids)))
        await session.execute(delete(Note).where(Note.round_id.in_(round_ids)))
        await session.execute(delete(Submission).where(Submission.round_id.in_(round_ids)))
        await session.execute(
            delete(SpotifyRoundPlaylist).where(SpotifyRoundPlaylist.round_id.in_(round_ids))
        )
        await session.execute(delete(Round).where(Round.id.in_(round_ids)))
    await session.execute(delete(LeagueMember).where(LeagueMember.league_id.in_(league_ids)))
    await session.execute(delete(League).where(League.id.in_(league_ids)))


async def add_submission(
    session,
    round_: Round,
    user: User,
    *,
    title: str,
    artist: str,
    isrc: str,
    mode: str = "playing",
    note: str | None = None,
) -> Submission:
    sub = Submission(
        round_id=round_.id,
        user_id=user.id,
        isrc=isrc,
        title=title,
        artist=artist,
        participation_mode=mode,
        note=note,
    )
    session.add(sub)
    await session.flush()
    return sub


def add_votes(session, round_: Round, submission: Submission, voters: list[User]) -> None:
    for voter in voters:
        session.add(Vote(round_id=round_.id, voter_id=voter.id, submission_id=submission.id))


def add_notes(
    session, round_: Round, submission: Submission, notes: list[tuple[User, str]]
) -> None:
    for author, body in notes:
        session.add(
            Note(round_id=round_.id, author_id=author.id, submission_id=submission.id, body=body)
        )


async def seed() -> None:
    async with async_session_factory() as session:
        dawn = await find_or_create_user(session, ORGANIZER_EMAIL, "Dawn")
        bo = await find_or_create_user(session, "bo@demo.test", "Bo")
        cy = await find_or_create_user(session, "cy@demo.test", "Cy")
        wren = await find_or_create_user(session, "wren@demo.test", "Wren")

        await wipe_existing_league(session)

        league = League(
            name=LEAGUE_NAME,
            description="a seeded demo — two closed rounds with results",
            organizer_id=dawn.id,
            total_rounds=4,
            votes_per_player=3,
            current_round=3,
            state="active",
        )
        session.add(league)
        await session.flush()

        for user in (dawn, bo, cy, wren):
            session.add(LeagueMember(league_id=league.id, user_id=user.id))

        # ---- Round 1: one clear winner, a different most-noted pick ---------- #
        r1 = Round(
            league_id=league.id,
            round_number=1,
            theme="late summer feels",
            description="the long golden evenings",
            state="closed",
            votes_per_player=3,
            closed_at=NOW - timedelta(days=7),
        )
        session.add(r1)
        await session.flush()

        r1_dawn = await add_submission(
            session,
            r1,
            dawn,
            title="Dreams",
            artist="Fleetwood Mac",
            isrc="USEE10001501",
            note="rumours never gets old",
        )
        r1_bo = await add_submission(
            session,
            r1,
            bo,
            title="Strange Currencies",
            artist="R.E.M.",
            isrc="USIR19400123",
            note="the most underrated R.E.M. track",
        )
        await add_submission(
            session,
            r1,
            cy,
            title="Teardrop",
            artist="Massive Attack",
            isrc="GBAAA9400456",
        )
        await add_submission(
            session,
            r1,
            wren,
            title="Such Great Heights",
            artist="The Postal Service",
            isrc="USX9P0300789",
            mode="vibing",
        )

        # Dawn wins the vote (3); Bo's pick draws the most notes (3).
        add_votes(session, r1, r1_dawn, [bo, cy, wren])
        add_votes(session, r1, r1_bo, [dawn])
        add_notes(
            session,
            r1,
            r1_bo,
            [
                (dawn, "that guitar line lives in my head"),
                (cy, "so good, instant add"),
                (wren, "didn't know this one — obsessed"),
            ],
        )
        add_notes(session, r1, r1_dawn, [(bo, "a classic for a reason")])

        # ---- Round 2: tie for the winner AND tie for most-noted -------------- #
        r2 = Round(
            league_id=league.id,
            round_number=2,
            theme="songs for the drive home",
            description="windows down, no destination",
            state="closed",
            votes_per_player=3,
            closed_at=NOW - timedelta(days=2),
        )
        session.add(r2)
        await session.flush()

        r2_dawn = await add_submission(
            session,
            r2,
            dawn,
            title="Pyramid Song",
            artist="Radiohead",
            isrc="GBAYE0101234",
        )
        r2_bo = await add_submission(
            session,
            r2,
            bo,
            title="Gypsy",
            artist="Fleetwood Mac",
            isrc="USEE10005678",
        )
        r2_cy = await add_submission(
            session,
            r2,
            cy,
            title="Holocene",
            artist="Bon Iver",
            isrc="USBON1100912",
        )

        # Dawn 2 votes, Bo 2 votes -> tie for first; Cy 1.
        add_votes(session, r2, r2_dawn, [bo, cy])
        add_votes(session, r2, r2_bo, [dawn, wren])
        add_votes(session, r2, r2_cy, [dawn])
        # Dawn's and Cy's picks each draw 2 notes -> most-noted tie.
        add_notes(
            session,
            r2,
            r2_dawn,
            [
                (cy, "those strings, come on"),
                (wren, "five-four time and it still floats"),
            ],
        )
        add_notes(
            session,
            r2,
            r2_cy,
            [
                (dawn, "cried a little, no regrets"),
                (bo, "perfect closer"),
            ],
        )

        # ---- Rounds 3 & 4: pending, to fill the slate ------------------------ #
        session.add(
            Round(
                league_id=league.id,
                round_number=3,
                theme=None,
                state="pending",
                votes_per_player=3,
            )
        )
        session.add(
            Round(
                league_id=league.id,
                round_number=4,
                theme=None,
                state="pending",
                votes_per_player=3,
            )
        )

        await session.commit()

        print(f"Seeded league '{LEAGUE_NAME}' ({league.id})")
        print(f"Organizer: {ORGANIZER_EMAIL} (sign in with this email to view it)")
        print("Round 1 closed -> winner Dawn, most noted 'Strange Currencies'")
        print("Round 2 closed -> winners Dawn & Bo, most noted 'Pyramid Song' & 'Holocene'")


if __name__ == "__main__":
    asyncio.run(seed())
