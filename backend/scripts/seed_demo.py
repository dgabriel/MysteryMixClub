"""Seed a local demo club for eyeballing the closed-mix reveal summary.

Creates (idempotently) a club "Demo Mixtape" owned by a known organizer email
with two CLOSED mixes wired to exercise the club-page winner / most-noted
card summary (MYS-65):

  - Mix 1 — a single clear winner (most votes) whose song is *not* the
    most-noted pick, so winner and most-noted differ.
  - Mix 2 — a TIE for the winner (two players level on votes) *and* a tie for
    most-noted (two songs level on notes), so both render their plural form.

Plus two trailing pending mixes to fill the slate.

Re-running wipes the prior "Demo Mixtape" club (and its mixes, submissions,
votes, notes, memberships) and rebuilds it; the demo users are reused.

Usage (from backend/, with the venv on PATH and Postgres up):
    python -m scripts.seed_demo
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.note import Note
from app.models.spotify_mix_playlist import SpotifyMixPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

# The organizer email is the local user's, so signing in with it (via the
# dev magic-link) lands you on this club as the organizer.
ORGANIZER_EMAIL = "dgabriel@gmail.com"
CLUB_NAME = "Demo Mixtape"

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


async def wipe_existing_club(session) -> None:
    club_ids = (
        (await session.execute(select(Club.id).where(Club.name == CLUB_NAME))).scalars().all()
    )
    if not club_ids:
        return
    mix_ids = (
        (await session.execute(select(Mix.id).where(Mix.club_id.in_(club_ids)))).scalars().all()
    )
    if mix_ids:
        await session.execute(delete(Vote).where(Vote.mix_id.in_(mix_ids)))
        await session.execute(delete(Note).where(Note.mix_id.in_(mix_ids)))
        await session.execute(delete(Submission).where(Submission.mix_id.in_(mix_ids)))
        await session.execute(
            delete(SpotifyMixPlaylist).where(SpotifyMixPlaylist.mix_id.in_(mix_ids))
        )
        await session.execute(delete(Mix).where(Mix.id.in_(mix_ids)))
    await session.execute(delete(ClubMember).where(ClubMember.club_id.in_(club_ids)))
    await session.execute(delete(Club).where(Club.id.in_(club_ids)))


async def add_submission(
    session,
    mix: Mix,
    user: User,
    *,
    title: str,
    artist: str,
    isrc: str,
    mode: str = "playing",
    note: str | None = None,
) -> Submission:
    sub = Submission(
        mix_id=mix.id,
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


def add_votes(session, mix: Mix, submission: Submission, voters: list[User]) -> None:
    for voter in voters:
        session.add(Vote(mix_id=mix.id, voter_id=voter.id, submission_id=submission.id))


def add_notes(session, mix: Mix, submission: Submission, notes: list[tuple[User, str]]) -> None:
    for author, body in notes:
        session.add(
            Note(mix_id=mix.id, author_id=author.id, submission_id=submission.id, body=body)
        )


async def seed() -> None:
    async with async_session_factory() as session:
        dawn = await find_or_create_user(session, ORGANIZER_EMAIL, "Dawn")
        bo = await find_or_create_user(session, "bo@demo.test", "Bo")
        cy = await find_or_create_user(session, "cy@demo.test", "Cy")
        wren = await find_or_create_user(session, "wren@demo.test", "Wren")

        await wipe_existing_club(session)

        club = Club(
            name=CLUB_NAME,
            description="a seeded demo — two closed mixes with results",
            organizer_id=dawn.id,
            total_mixes=4,
            votes_per_player=3,
            current_mix=3,
            state="active",
        )
        session.add(club)
        await session.flush()

        for user in (dawn, bo, cy, wren):
            session.add(ClubMember(club_id=club.id, user_id=user.id))

        # ---- Mix 1: one clear winner, a different most-noted pick ------------ #
        m1 = Mix(
            club_id=club.id,
            mix_number=1,
            theme="late summer feels",
            description="the long golden evenings",
            state="closed",
            votes_per_player=3,
            closed_at=NOW - timedelta(days=7),
        )
        session.add(m1)
        await session.flush()

        m1_dawn = await add_submission(
            session,
            m1,
            dawn,
            title="Dreams",
            artist="Fleetwood Mac",
            isrc="USEE10001501",
            note="rumours never gets old",
        )
        m1_bo = await add_submission(
            session,
            m1,
            bo,
            title="Strange Currencies",
            artist="R.E.M.",
            isrc="USIR19400123",
            note="the most underrated R.E.M. track",
        )
        await add_submission(
            session,
            m1,
            cy,
            title="Teardrop",
            artist="Massive Attack",
            isrc="GBAAA9400456",
        )
        await add_submission(
            session,
            m1,
            wren,
            title="Such Great Heights",
            artist="The Postal Service",
            isrc="USX9P0300789",
            mode="vibing",
        )

        # Dawn wins the vote (3); Bo's pick draws the most notes (3).
        add_votes(session, m1, m1_dawn, [bo, cy, wren])
        add_votes(session, m1, m1_bo, [dawn])
        add_notes(
            session,
            m1,
            m1_bo,
            [
                (dawn, "that guitar line lives in my head"),
                (cy, "so good, instant add"),
                (wren, "didn't know this one — obsessed"),
            ],
        )
        add_notes(session, m1, m1_dawn, [(bo, "a classic for a reason")])

        # ---- Mix 2: tie for the winner AND tie for most-noted ----------------- #
        m2 = Mix(
            club_id=club.id,
            mix_number=2,
            theme="songs for the drive home",
            description="windows down, no destination",
            state="closed",
            votes_per_player=3,
            closed_at=NOW - timedelta(days=2),
        )
        session.add(m2)
        await session.flush()

        m2_dawn = await add_submission(
            session,
            m2,
            dawn,
            title="Pyramid Song",
            artist="Radiohead",
            isrc="GBAYE0101234",
        )
        m2_bo = await add_submission(
            session,
            m2,
            bo,
            title="Gypsy",
            artist="Fleetwood Mac",
            isrc="USEE10005678",
        )
        m2_cy = await add_submission(
            session,
            m2,
            cy,
            title="Holocene",
            artist="Bon Iver",
            isrc="USBON1100912",
        )

        # Dawn 2 votes, Bo 2 votes -> tie for first; Cy 1.
        add_votes(session, m2, m2_dawn, [bo, cy])
        add_votes(session, m2, m2_bo, [dawn, wren])
        add_votes(session, m2, m2_cy, [dawn])
        # Dawn's and Cy's picks each draw 2 notes -> most-noted tie.
        add_notes(
            session,
            m2,
            m2_dawn,
            [
                (cy, "those strings, come on"),
                (wren, "five-four time and it still floats"),
            ],
        )
        add_notes(
            session,
            m2,
            m2_cy,
            [
                (dawn, "cried a little, no regrets"),
                (bo, "perfect closer"),
            ],
        )

        # ---- Mixes 3 & 4: pending, to fill the slate --------------------------- #
        session.add(
            Mix(
                club_id=club.id,
                mix_number=3,
                theme=None,
                state="pending",
                votes_per_player=3,
            )
        )
        session.add(
            Mix(
                club_id=club.id,
                mix_number=4,
                theme=None,
                state="pending",
                votes_per_player=3,
            )
        )

        await session.commit()

        print(f"Seeded club '{CLUB_NAME}' ({club.id})")
        print(f"Organizer: {ORGANIZER_EMAIL} (sign in with this email to view it)")
        print("Mix 1 closed -> winner Dawn, most noted 'Strange Currencies'")
        print("Mix 2 closed -> winners Dawn & Bo, most noted 'Pyramid Song' & 'Holocene'")


if __name__ == "__main__":
    asyncio.run(seed())
