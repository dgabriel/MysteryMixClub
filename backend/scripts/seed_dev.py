"""Seed a full local dev dataset: three clubs spanning the whole mix lifecycle.

Replaces the old single-club `seed_demo.py`, which only built two closed mixes and
so covered none of the in-flight states worth eyeballing.

What it builds (all owned by a shared cast of 11, Dawn included):

  1. "Basement Tapes"    — COMPLETE. 4 mixes, all closed, club.state="complete".
  2. "Friday Mixtape"    — active, 5 mixes: 3 closed, mix 4 OPEN FOR SUBMISSIONS,
                           mix 5 pending.
  3. "The Long Play"     — active, 12 mixes: 10 closed, mix 11 OPEN FOR VOTING,
                           mix 12 pending. **Dawn organizes this one.**

Dawn is a member of all three and the organizer of "The Long Play" only, which
is the club whose mix is open for voting.

Two deliberate properties of the open-voting mix, both of which matter for
testing the ballot:

  * Dawn has NO votes in it, because the ballot only renders while your vote set
    is empty — with votes cast you get the tally instead.
  * Four other playing submitters have not voted either, so Dawn casting a vote
    cannot satisfy `voting_quorum_met` and auto-close the mix out from under the
    thing being tested.

Emails are `@example.com`, NOT `@demo.test`: `.test` is a reserved TLD and
`email_validator` rejects it, so the old seed users could never actually sign
in (every /auth/request for one 422'd).

DESTRUCTIVE: this wipes EVERY club in the target database and rebuilds these
three. That is the point — it defines what the local dev dataset is, and a
partial wipe leaves behind the drift it exists to clear. Users are reused, never
deleted. Pass --keep-others to wipe only the three seeded clubs by name.

Local dev only. It talks to whatever DATABASE_URL points at, so do not run it
anywhere you would mind losing every club.

Usage (from backend/, with Postgres up):
    .venv/bin/python -m scripts.seed_dev
    .venv/bin/python -m scripts.seed_dev --keep-others
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.apple_mix_playlist import AppleMixPlaylist
from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.invite import Invite
from app.models.mix import Mix
from app.models.note import Note
from app.models.playlist_job import PlaylistJob
from app.models.spotify_mix_playlist import SpotifyMixPlaylist
from app.models.submission import Submission
from app.models.user import User
from app.models.vote import Vote

# Dawn's real address, so the dev magic-link lands on these clubs as herself.
ORGANIZER_EMAIL = "dgabriel@gmail.com"

NOW = datetime.now(timezone.utc)

# Deterministic: re-seeding should produce the same leaderboards, otherwise
# "did my change alter the results?" is unanswerable.
RNG = random.Random(20260813)

COMPLETED_CLUB = "Basement Tapes"
SUBMITTING_CLUB = "Friday Mixtape"
VOTING_CLUB = "The Long Play"
CLUB_NAMES = (COMPLETED_CLUB, SUBMITTING_CLUB, VOTING_CLUB)

# 10 supporting players + Dawn = 11 members per club. One cast across all three
# so leaderboards are comparable and you always recognise the names.
CAST = [
    ("bo@example.com", "Bo"),
    ("cy@example.com", "Cy"),
    ("wren@example.com", "Wren"),
    ("ida@example.com", "Ida"),
    ("juno@example.com", "Juno"),
    ("kit@example.com", "Kit"),
    ("mars@example.com", "Mars"),
    ("nell@example.com", "Nell"),
    ("otis@example.com", "Otis"),
    ("saff@example.com", "Saff"),
]

# Enough tracks that no mix repeats itself. (title, artist, album, isrc)
SONGS = [
    ("Dreams", "Fleetwood Mac", "Rumours", "USEE10001501"),
    ("Strange Currencies", "R.E.M.", "Monster", "USIR19400123"),
    ("Teardrop", "Massive Attack", "Mezzanine", "GBAAA9400456"),
    ("Africa", "Toto", "Toto IV", "USSM18200150"),
    ("Wuthering Heights", "Kate Bush", "The Kick Inside", "GBAYE7800123"),
    ("Just a Friend", "Biz Markie", "The Biz Never Sleeps", "USWB19900321"),
    ("Pyramid Song", "Radiohead", "Amnesiac", "GBAYE0100234"),
    ("Redbone", "Childish Gambino", "Awaken, My Love!", "USUM71614948"),
    ("Marquee Moon", "Television", "Marquee Moon", "USEE17700345"),
    ("This Must Be the Place", "Talking Heads", "Speaking in Tongues", "USSM18300456"),
    ("Cranes in the Sky", "Solange", "A Seat at the Table", "USSM11603210"),
    ("Debaser", "Pixies", "Doolittle", "USBEE8900567"),
    ("Nightcall", "Kavinsky", "OutRun", "FR6V81000123"),
    ("Alright", "Kendrick Lamar", "To Pimp a Butterfly", "USUM71502549"),
    ("Gymnopédie No. 1", "Erik Satie", "Trois Gymnopédies", "FRZ127300001"),
    ("Motion Picture Soundtrack", "Radiohead", "Kid A", "GBAYE0000789"),
    ("Hounds of Love", "Kate Bush", "Hounds of Love", "GBAYE8500234"),
    ("Beautiful Ones", "Suede", "Coming Up", "GBAAA9600678"),
    ("Tom's Diner", "Suzanne Vega", "Solitude Standing", "USAM18700345"),
    ("Roygbiv", "Boards of Canada", "Music Has the Right", "GBCEL9800123"),
    ("Cissy Strut", "The Meters", "The Meters", "USWB16900234"),
    ("Fake Plastic Trees", "Radiohead", "The Bends", "GBAYE9500345"),
    ("Sabotage", "Beastie Boys", "Ill Communication", "USCA29400456"),
    ("Only Shallow", "My Bloody Valentine", "Loveless", "GBAAA9100567"),
    ("Rid of Me", "PJ Harvey", "Rid of Me", "GBAAA9300678"),
    ("Enjoy the Silence", "Depeche Mode", "Violator", "GBAAA9000789"),
    ("Ceremony", "New Order", "Ceremony", "GBAAA8100890"),
    ("Idioteque", "Radiohead", "Kid A", "GBAYE0000901"),
    ("Bizarre Love Triangle", "New Order", "Brotherhood", "GBAAA8600012"),
    ("A Forest", "The Cure", "Seventeen Seconds", "GBAAA8000123"),
]

THEMES = [
    ("late summer feels", "the long golden evenings"),
    ("songs to drive to", "windows down, no destination"),
    ("a song that changed your mind", "about a band, a genre, anything"),
    ("rain music", "for the grey afternoons"),
    ("the first track you loved", "whatever you were, whenever that was"),
    ("something from before you were born", "borrowed nostalgia"),
    ("a song with a great bassline", "you know the one"),
    ("under three minutes", "brevity as a discipline"),
    ("music for cooking to", "chopping tempo"),
    ("a track that should have been a hit", "and never was"),
    ("cover versions only", "better than the original, ideally"),
    ("close the year out", "whatever that means to you"),
    ("late night, headphones", "the small hours"),
]

NOTE_BODIES = [
    "this is a genuinely perfect pick",
    "how have I never heard this before",
    "instant add to the rotation",
    "the bassline alone earns the vote",
    "took a couple of listens but it got me",
    "played this three times in a row",
    "exactly the brief, well done",
    "this one is going to live with me",
    "unbelievable that this wasn't a hit",
    "the production on this is ridiculous",
]


async def find_or_create_user(session, email: str, display_name: str) -> User:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name=display_name)
        session.add(user)
        await session.flush()
    elif not user.display_name:
        # Existing-but-not-onboarded account: name it so it shows up in lists.
        user.display_name = display_name
    return user


async def wipe_clubs(session, names: tuple[str, ...] | None) -> None:
    """Delete clubs and everything hanging off them, in FK order.

    `names=None` wipes EVERY club, which is the default: this script defines
    what the local dev dataset is, and a partial wipe leaves exactly the drift
    it exists to clear (13 clubs had accumulated from past manual testing,
    all of them showing up on /home alongside the seeded ones). Pass
    --keep-others to wipe only the three seeded names instead.
    """
    stmt = select(Club.id) if names is None else select(Club.id).where(Club.name.in_(names))
    club_ids = (await session.execute(stmt)).scalars().all()
    if not club_ids:
        return
    mix_ids = (
        (await session.execute(select(Mix.id).where(Mix.club_id.in_(club_ids)))).scalars().all()
    )
    if mix_ids:
        # Every table with an FK to mixes, or this fails partway through. The
        # full list is worth keeping accurate — the first cut missed
        # playlist_jobs and apple_mix_playlists and blew up mid-wipe. To
        # re-derive it after a schema change:
        #   SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
        #   JOIN information_schema.key_column_usage kcu USING (constraint_name)
        #   JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
        #   WHERE tc.constraint_type='FOREIGN KEY' AND ccu.table_name='mixes';
        await session.execute(delete(Vote).where(Vote.mix_id.in_(mix_ids)))
        await session.execute(delete(Note).where(Note.mix_id.in_(mix_ids)))
        await session.execute(delete(Submission).where(Submission.mix_id.in_(mix_ids)))
        await session.execute(
            delete(SpotifyMixPlaylist).where(SpotifyMixPlaylist.mix_id.in_(mix_ids))
        )
        await session.execute(delete(AppleMixPlaylist).where(AppleMixPlaylist.mix_id.in_(mix_ids)))
        await session.execute(delete(PlaylistJob).where(PlaylistJob.mix_id.in_(mix_ids)))
        await session.execute(delete(Mix).where(Mix.id.in_(mix_ids)))
    await session.execute(delete(ClubMember).where(ClubMember.club_id.in_(club_ids)))
    await session.execute(delete(Invite).where(Invite.club_id.in_(club_ids)))
    await session.execute(delete(Club).where(Club.id.in_(club_ids)))


def song_for(mix_number: int, seat: int) -> tuple[str, str, str, str]:
    """A stable, non-repeating song per (mix, seat) slot."""
    return SONGS[(mix_number * 7 + seat * 3) % len(SONGS)]


async def build_closed_mix(
    session,
    club: Club,
    mix_number: int,
    members: list[User],
    *,
    closed_days_ago: int,
) -> Mix:
    """A finished mix: everyone submitted, everyone voted, some notes left.

    Votes are weighted (ADR 0014) — a couple of players stack two on one song,
    which is what makes the reveal and the leaderboard worth looking at.
    """
    theme, description = THEMES[mix_number % len(THEMES)]
    opened = NOW - timedelta(days=closed_days_ago + 6)
    mix = Mix(
        club_id=club.id,
        mix_number=mix_number,
        theme=theme,
        description=description,
        state="closed",
        votes_per_player=club.votes_per_player,
        submission_opened_at=opened,
        submission_deadline=opened + timedelta(hours=club.submission_window_hours),
        voting_deadline=opened + timedelta(hours=club.submission_window_hours + 72),
        closed_at=NOW - timedelta(days=closed_days_ago),
    )
    session.add(mix)
    await session.flush()

    # One submission each. A single viber per mix keeps the casual-mode path
    # represented without distorting the results.
    viber = members[mix_number % len(members)]
    subs: list[Submission] = []
    for seat, member in enumerate(members):
        title, artist, album, isrc = song_for(mix_number, seat)
        sub = Submission(
            mix_id=mix.id,
            user_id=member.id,
            isrc=isrc,
            title=title,
            artist=artist,
            album=album,
            participation_mode="vibing" if member is viber else "playing",
            note=RNG.choice([None, "an easy pick this week", "took me a while to land on this"]),
            created_at=opened + timedelta(hours=RNG.randint(1, 40)),
        )
        session.add(sub)
        subs.append(sub)
    await session.flush()

    # Everyone playing spends their full allowance on other people's songs.
    for member in members:
        if member is viber:
            continue  # vibers sit voting out
        options = [s for s in subs if s.user_id != member.id]
        allowance = club.votes_per_player
        # Roughly a third of players stack two votes on one song rather than
        # spreading them, so weights above 1 actually appear in the data.
        if RNG.random() < 0.34 and allowance >= 2:
            favourite = RNG.choice(options)
            session.add(
                Vote(
                    mix_id=mix.id,
                    voter_id=member.id,
                    submission_id=favourite.id,
                    weight=2,
                )
            )
            rest = [s for s in options if s.id != favourite.id]
            for pick in RNG.sample(rest, min(allowance - 2, len(rest))):
                session.add(
                    Vote(mix_id=mix.id, voter_id=member.id, submission_id=pick.id, weight=1)
                )
        else:
            for pick in RNG.sample(options, min(allowance, len(options))):
                session.add(
                    Vote(mix_id=mix.id, voter_id=member.id, submission_id=pick.id, weight=1)
                )

    # Notes: a handful per mix, at most one per (author, submission) — there is
    # a unique constraint on that pair.
    for _ in range(RNG.randint(4, 9)):
        author = RNG.choice(members)
        target = RNG.choice([s for s in subs if s.user_id != author.id])
        exists = await session.scalar(
            select(Note.id).where(Note.author_id == author.id, Note.submission_id == target.id)
        )
        if exists is None:
            session.add(
                Note(
                    mix_id=mix.id,
                    author_id=author.id,
                    submission_id=target.id,
                    body=RNG.choice(NOTE_BODIES),
                )
            )
    return mix


async def seed(*, keep_others: bool = False) -> None:
    async with async_session_factory() as session:
        dawn = await find_or_create_user(session, ORGANIZER_EMAIL, "Dawn")
        others = [await find_or_create_user(session, email, name) for email, name in CAST]
        members = [dawn, *others]  # 11
        assert len(members) == 11, len(members)

        await wipe_clubs(session, CLUB_NAMES if keep_others else None)

        # ------------------------------------------------------------------ #
        # 1. A completed club — every mix closed, club.state == "complete".
        # ------------------------------------------------------------------ #
        done = Club(
            name=COMPLETED_CLUB,
            description="a finished season, kept for the archive",
            organizer_id=others[0].id,  # Bo ran this one
            total_mixes=4,
            votes_per_player=3,
            current_mix=4,
            state="complete",
            completed_at=NOW - timedelta(days=20),
        )
        session.add(done)
        await session.flush()
        for member in members:
            session.add(ClubMember(club_id=done.id, user_id=member.id))
        for n in range(1, 5):
            await build_closed_mix(session, done, n, members, closed_days_ago=20 + (4 - n) * 9)

        # ------------------------------------------------------------------ #
        # 2. Mid-season, currently taking submissions.
        #    3 closed, mix 4 open_submission, mix 5 pending.
        # ------------------------------------------------------------------ #
        submitting = Club(
            name=SUBMITTING_CLUB,
            description="three down, one open for songs right now",
            organizer_id=others[1].id,  # Cy runs this one
            total_mixes=5,
            votes_per_player=3,
            current_mix=4,
            state="active",
        )
        session.add(submitting)
        await session.flush()
        for member in members:
            session.add(ClubMember(club_id=submitting.id, user_id=member.id))
        for n in range(1, 4):
            await build_closed_mix(session, submitting, n, members, closed_days_ago=9 + (3 - n) * 9)

        opened = NOW - timedelta(hours=18)
        m4 = Mix(
            club_id=submitting.id,
            mix_number=4,
            theme=THEMES[4][0],
            description=THEMES[4][1],
            state="open_submission",
            votes_per_player=3,
            submission_opened_at=opened,
            submission_deadline=NOW + timedelta(hours=54),
        )
        session.add(m4)
        await session.flush()
        # Six of eleven have submitted so far — Dawn deliberately has NOT, so
        # the submit form is what she lands on.
        for seat, member in enumerate(others[:6]):
            title, artist, album, isrc = song_for(4, seat)
            session.add(
                Submission(
                    mix_id=m4.id,
                    user_id=member.id,
                    isrc=isrc,
                    title=title,
                    artist=artist,
                    album=album,
                    participation_mode="playing",
                    created_at=opened + timedelta(hours=seat),
                )
            )
        # Mix 5 waits its turn, themed so it is ready to open.
        session.add(
            Mix(
                club_id=submitting.id,
                mix_number=5,
                theme=THEMES[5][0],
                description=THEMES[5][1],
                state="pending",
                votes_per_player=3,
            )
        )

        # ------------------------------------------------------------------ #
        # 3. The long-running club Dawn organizes — currently OPEN FOR VOTING.
        #    10 closed, mix 11 open_voting, mix 12 pending.
        # ------------------------------------------------------------------ #
        voting = Club(
            name=VOTING_CLUB,
            description="ten mixes deep, and one on the ballot right now",
            organizer_id=dawn.id,
            total_mixes=12,
            votes_per_player=3,
            current_mix=11,
            state="active",
        )
        session.add(voting)
        await session.flush()
        for member in members:
            session.add(
                ClubMember(
                    club_id=voting.id,
                    user_id=member.id,
                    # Dawn is organizer via organizer_id; her member row stays
                    # "member", which is what the role endpoint expects.
                    role="member",
                )
            )
        for n in range(1, 11):
            await build_closed_mix(session, voting, n, members, closed_days_ago=6 + (10 - n) * 7)

        sub_opened = NOW - timedelta(days=4)
        m11 = Mix(
            club_id=voting.id,
            mix_number=11,
            theme=THEMES[11][0],
            description=THEMES[11][1],
            state="open_voting",
            votes_per_player=3,
            submission_opened_at=sub_opened,
            submission_deadline=NOW - timedelta(days=1),
            voting_deadline=NOW + timedelta(hours=48),
        )
        session.add(m11)
        await session.flush()
        ballot: list[Submission] = []
        for seat, member in enumerate(members):
            title, artist, album, isrc = song_for(11, seat)
            sub = Submission(
                mix_id=m11.id,
                user_id=member.id,
                isrc=isrc,
                title=title,
                artist=artist,
                album=album,
                participation_mode="playing",
                note=None if seat % 3 else "curious what everyone makes of this one",
                created_at=sub_opened + timedelta(hours=seat * 2),
            )
            session.add(sub)
            ballot.append(sub)
        await session.flush()

        # Six of the ten non-Dawn members have voted. Dawn has none, so the
        # BALLOT renders rather than the tally; and four playing submitters are
        # still outstanding, so Dawn casting hers cannot meet quorum and
        # auto-close the mix mid-test.
        for member in others[:6]:
            options = [s for s in ballot if s.user_id != member.id]
            if RNG.random() < 0.4:
                favourite = RNG.choice(options)
                session.add(
                    Vote(mix_id=m11.id, voter_id=member.id, submission_id=favourite.id, weight=2)
                )
                rest = [s for s in options if s.id != favourite.id]
                for pick in RNG.sample(rest, 1):
                    session.add(
                        Vote(mix_id=m11.id, voter_id=member.id, submission_id=pick.id, weight=1)
                    )
            else:
                for pick in RNG.sample(options, 3):
                    session.add(
                        Vote(mix_id=m11.id, voter_id=member.id, submission_id=pick.id, weight=1)
                    )

        session.add(
            Mix(
                club_id=voting.id,
                mix_number=12,
                theme=THEMES[12][0],
                description=THEMES[12][1],
                state="pending",
                votes_per_player=3,
            )
        )

        await session.commit()

        print(f"seeded {len(members)} members across 3 clubs:")
        print(f"  {COMPLETED_CLUB:<16} complete — 4/4 mixes closed (organizer: Bo)")
        print(f"  {SUBMITTING_CLUB:<16} active   — 3 closed, mix 4 OPEN FOR SUBMISSIONS, 5 pending")
        print(f"  {VOTING_CLUB:<16} active   — 10 closed, mix 11 OPEN FOR VOTING, 12 pending")
        print(f"                   ^ organized by Dawn <{ORGANIZER_EMAIL}>, no votes cast yet")


if __name__ == "__main__":
    import sys

    asyncio.run(seed(keep_others="--keep-others" in sys.argv))
