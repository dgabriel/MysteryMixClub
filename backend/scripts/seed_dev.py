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
from app.models.waitlist_entry import WaitlistEntry

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

# Real catalogue metadata, resolved once against Deezer (the app's own provider,
# so the ISRCs and covers are exactly what a real submission carries), iTunes
# (for the Apple Music deep link), and YouTube (for youtube_video_id). Baked in
# as constants rather than fetched at seed time so seeding stays offline, fast
# and deterministic. Reissue markers like "(2004 Remaster)" were stripped from
# titles; "(Naive Melody)" is genuine.
#
# `links` mirrors the keys production stores in submissions.platform_links
# (app/services/song_links.py): exact URLs for Deezer, Apple Music, and YouTube
# (watch?v=<youtube_video_id>, matching what SongLinkAssembler produces once a
# submission is resolved), keyless search deeplinks for the rest (Spotify has
# no keyless exact-link path at all — see technical-design.md §8).
#
# youtube_video_id is baked in here specifically because it's the one field
# that DIDN'T get this treatment historically: every seeded submission landed
# with it NULL, so the backfill worker resolved all ~200 of them against the
# live YouTube Data API on every reseed — two full days of that key's 100/day
# search.list quota to reseed once (MysteryMixClub-t2ai). Setting it (plus
# youtube_lookup_attempted_at, in make_submission below) marks every catalogue
# submission as already resolved, so a fresh seed leaves nothing pending.
SONGS: list[dict[str, object]] = [
    {
        "title": "Dreams",
        "artist": "Fleetwood Mac",
        "album": "Rumours",
        "isrc": "USWB10400046",
        "youtube_video_id": "Y3ywicffOj4",
        "art": "https://cdn-images.dzcdn.net/images/cover/9732751ce91d786dcf30069853697078/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Dreams%20%282004%20Remaster%29%20Fleetwood%20Mac",
            "appleMusic": "https://music.apple.com/us/album/dreams/202271826?i=202272624&uo=4",
            "deezer": "https://www.deezer.com/track/63480987",
            "youtube": "https://www.youtube.com/watch?v=Y3ywicffOj4",
            "youtubeMusic": "https://music.youtube.com/watch?v=Y3ywicffOj4",
        },
    },
    {
        "title": "Strange Currencies",
        "artist": "R.E.M.",
        "album": "Monster",
        "isrc": "USC4R1901438",
        "youtube_video_id": "j4iuG7StmPc",
        "art": "https://cdn-images.dzcdn.net/images/cover/048a11a44a2fe965430c4f0a89a9f49e/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Strange%20Currencies%20%28Remastered%202013%29%20R.E.M.",
            "appleMusic": "https://music.apple.com/us/album/strange-currencies-remastered/1484709966?i=1484709990&uo=4",
            "deezer": "https://www.deezer.com/track/788658472",
            "youtube": "https://www.youtube.com/watch?v=j4iuG7StmPc",
            "youtubeMusic": "https://music.youtube.com/watch?v=j4iuG7StmPc",
        },
    },
    {
        "title": "Teardrop",
        "artist": "Massive Attack",
        "album": "Mezzanine",
        "isrc": "GBAAA9800322",
        "youtube_video_id": "u7K72X4eo_s",
        "art": "https://cdn-images.dzcdn.net/images/cover/85abbdc3ed4a7b94ace97f868fe70f63/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Teardrop%20Massive%20Attack",
            "appleMusic": "https://music.apple.com/us/album/teardrop/724466069?i=724466700&uo=4",
            "deezer": "https://www.deezer.com/track/3129748",
            "youtube": "https://www.youtube.com/watch?v=u7K72X4eo_s",
            "youtubeMusic": "https://music.youtube.com/watch?v=u7K72X4eo_s",
        },
    },
    {
        "title": "Africa",
        "artist": "Toto",
        "album": "Toto IV",
        "isrc": "USSM19801941",
        "youtube_video_id": "FTQbiNvZqaY",
        "art": "https://cdn-images.dzcdn.net/images/cover/153332e88a14255a8c3d5959a5a21882/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Africa%20Toto",
            "appleMusic": "https://music.apple.com/us/album/africa/185716551?i=185717604&uo=4",
            "deezer": "https://www.deezer.com/track/1079668",
            "youtube": "https://www.youtube.com/watch?v=FTQbiNvZqaY",
            "youtubeMusic": "https://music.youtube.com/watch?v=FTQbiNvZqaY",
        },
    },
    {
        "title": "Wuthering Heights",
        "artist": "Kate Bush",
        "album": "The Kick Inside",
        "isrc": "GBAYE7700223",
        "youtube_video_id": "uVz2i-w2vz8",
        "art": "https://cdn-images.dzcdn.net/images/cover/4cf15986426e5e453e38edf60bc1b6ba/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Wuthering%20Heights%20Kate%20Bush",
            "appleMusic": "https://music.apple.com/us/album/wuthering-heights/1675380115?i=1675380129&uo=4",
            "deezer": "https://www.deezer.com/track/2173947547",
            "youtube": "https://www.youtube.com/watch?v=uVz2i-w2vz8",
            "youtubeMusic": "https://music.youtube.com/watch?v=uVz2i-w2vz8",
        },
    },
    {
        "title": "Just a Friend",
        "artist": "Biz Markie",
        "album": "Biz's Baddest Beats: The Best of Biz Markie",
        "isrc": "USRH10902676",
        "youtube_video_id": "9aofoBrFNdg",
        "art": "https://cdn-images.dzcdn.net/images/cover/59d14483d167ceb8465cb1ef1ccad0d0/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Just%20a%20Friend%20Biz%20Markie",
            "appleMusic": "https://music.apple.com/us/album/just-a-friend/316484158?i=316484656&uo=4",
            "deezer": "https://www.deezer.com/track/6627454",
            "youtube": "https://www.youtube.com/watch?v=9aofoBrFNdg",
            "youtubeMusic": "https://music.youtube.com/watch?v=9aofoBrFNdg",
        },
    },
    {
        "title": "Pyramid Song",
        "artist": "Radiohead",
        "album": "Amnesiac",
        "isrc": "GBAYE0001578",
        "youtube_video_id": "3M_Gg1xAHE4",
        "art": "https://cdn-images.dzcdn.net/images/cover/d611b9ef9d7ce87a74c697d74be5ae15/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Pyramid%20Song%20Radiohead",
            "appleMusic": "https://music.apple.com/us/album/pyramid-song/1097864180?i=1097864572&uo=4",
            "deezer": "https://www.deezer.com/track/138540337",
            "youtube": "https://www.youtube.com/watch?v=3M_Gg1xAHE4",
            "youtubeMusic": "https://music.youtube.com/watch?v=3M_Gg1xAHE4",
        },
    },
    {
        "title": "Redbone",
        "artist": "Childish Gambino",
        "album": '"Awaken, My Love!"',
        "isrc": "USYAH1600107",
        "youtube_video_id": "aMi2vCN9j_g",
        "art": "https://cdn-images.dzcdn.net/images/cover/57ae3715e73c0486616bab8c2d6c6159/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Redbone%20Childish%20Gambino",
            "appleMusic": "https://music.apple.com/us/album/redbone-mixed/1738095441?i=1738095468&uo=4",
            "deezer": "https://www.deezer.com/track/3025966451",
            "youtube": "https://www.youtube.com/watch?v=aMi2vCN9j_g",
            "youtubeMusic": "https://music.youtube.com/watch?v=aMi2vCN9j_g",
        },
    },
    {
        "title": "Marquee Moon",
        "artist": "Television",
        "album": "Marquee Moon",
        "isrc": "USEE10181884",
        "youtube_video_id": "jlbunmCbTBA",
        "art": "https://cdn-images.dzcdn.net/images/cover/ee22cb01343143b8d78c63e2aa53c2b3/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Marquee%20Moon%20Television",
            "appleMusic": "https://music.apple.com/us/album/marquee-moon/1049069472?i=1049069476&uo=4",
            "deezer": "https://www.deezer.com/track/718312",
            "youtube": "https://www.youtube.com/watch?v=jlbunmCbTBA",
            "youtubeMusic": "https://music.youtube.com/watch?v=jlbunmCbTBA",
        },
    },
    {
        "title": "This Must Be the Place (Naive Melody)",
        "artist": "Talking Heads",
        "album": "Speaking in Tongues",
        "isrc": "USWB10502911",
        "youtube_video_id": "Fb2q141rMNE",
        "art": "https://cdn-images.dzcdn.net/images/cover/70db13b9aec041ca74d0ec2b815846e9/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/This%20Must%20Be%20the%20Place%20%28Naive%20Melody%29%20%282005%20Remaster%29%20Talking%20Heads",
            "appleMusic": "https://music.apple.com/us/album/this-must-be-the-place-naive-melody/20833651?i=20833681&uo=4",
            "deezer": "https://www.deezer.com/track/3614317",
            "youtube": "https://www.youtube.com/watch?v=Fb2q141rMNE",
            "youtubeMusic": "https://music.youtube.com/watch?v=Fb2q141rMNE",
        },
    },
    {
        "title": "Cranes in the Sky",
        "artist": "Solange",
        "album": "A Seat at the Table",
        "isrc": "USSM11607807",
        "youtube_video_id": "S0qrinhNnOM",
        "art": "https://cdn-images.dzcdn.net/images/cover/36b361c2c916b333a0b7c6f949c32099/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Cranes%20in%20the%20Sky%20Solange",
            "appleMusic": "https://music.apple.com/us/album/cranes-in-the-sky/1159507212?i=1159507287&uo=4",
            "deezer": "https://www.deezer.com/track/133103636",
            "youtube": "https://www.youtube.com/watch?v=S0qrinhNnOM",
            "youtubeMusic": "https://music.youtube.com/watch?v=S0qrinhNnOM",
        },
    },
    {
        "title": "Debaser",
        "artist": "Pixies",
        "album": "Death to the Pixies",
        "isrc": "GBAFL9700091",
        "youtube_video_id": "PVyS9JwtFoQ",
        "art": "https://cdn-images.dzcdn.net/images/cover/f2ea8050f0540c5f08316832cf9ec2cb/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Debaser%20Pixies",
            "appleMusic": "https://music.apple.com/us/album/debaser/7060469?i=7060439&uo=4",
            "deezer": "https://www.deezer.com/track/936881",
            "youtube": "https://www.youtube.com/watch?v=PVyS9JwtFoQ",
            "youtubeMusic": "https://music.youtube.com/watch?v=PVyS9JwtFoQ",
        },
    },
    {
        "title": "Nightcall",
        "artist": "Kavinsky",
        "album": "Nightcall",
        "isrc": "FRS710900410",
        "youtube_video_id": "ZVS6Q_lbKQ0",
        "art": "https://cdn-images.dzcdn.net/images/cover/7f9ecda862091716e4e8f74a7e115f93/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Nightcall%20Kavinsky",
            "appleMusic": "https://music.apple.com/us/album/nightcall/1442447952?i=1442447970&uo=4",
            "deezer": "https://www.deezer.com/track/62496771",
            "youtube": "https://www.youtube.com/watch?v=ZVS6Q_lbKQ0",
            "youtubeMusic": "https://music.youtube.com/watch?v=ZVS6Q_lbKQ0",
        },
    },
    {
        "title": "Alright",
        "artist": "Kendrick Lamar",
        "album": "To Pimp A Butterfly",
        "isrc": "USUM71502498",
        "youtube_video_id": "Z-48u_uWMHY",
        "art": "https://cdn-images.dzcdn.net/images/cover/00dd0da365a94b1829302d6b7fec70e6/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Alright%20Kendrick%20Lamar",
            "appleMusic": "https://music.apple.com/us/album/alright/1440871877?i=1440871886&uo=4",
            "deezer": "https://www.deezer.com/track/97206068",
            "youtube": "https://www.youtube.com/watch?v=Z-48u_uWMHY",
            "youtubeMusic": "https://music.youtube.com/watch?v=Z-48u_uWMHY",
        },
    },
    {
        "title": "Gymnop\u00e9die No. 1",
        "artist": "Erik Satie",
        "album": "Gymnop\u00e9dies",
        "isrc": "TCABB1109123",
        "youtube_video_id": "cic1RNHXa-k",
        "art": "https://cdn-images.dzcdn.net/images/cover/29e7eed1c4a83283ca354f6541fd56f6/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Gymnop%C3%A9die%20No.%201%20Erik%20Satie",
            "appleMusic": "https://music.apple.com/us/album/gymnop%C3%A9die-no-1-erik-satie/1607396597?i=1607396598&uo=4",
            "deezer": "https://www.deezer.com/track/75009998",
            "youtube": "https://www.youtube.com/watch?v=cic1RNHXa-k",
            "youtubeMusic": "https://music.youtube.com/watch?v=cic1RNHXa-k",
        },
    },
    {
        "title": "Motion Picture Soundtrack",
        "artist": "Radiohead",
        "album": "Kid A",
        "isrc": "GBAYE0800814",
        "youtube_video_id": "EcSvMFm2ABE",
        "art": "https://cdn-images.dzcdn.net/images/cover/e5925065cdb1cefbc3bd75af4a1f1801/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Motion%20Picture%20Soundtrack%20Radiohead",
            "appleMusic": "https://music.apple.com/us/album/motion-picture-soundtrack/1581785974?i=1581786358&uo=4",
            "deezer": "https://www.deezer.com/track/138547605",
            "youtube": "https://www.youtube.com/watch?v=EcSvMFm2ABE",
            "youtubeMusic": "https://music.youtube.com/watch?v=EcSvMFm2ABE",
        },
    },
    {
        "title": "Hounds Of Love",
        "artist": "Kate Bush",
        "album": "Hounds Of Love",
        "isrc": "GBCNR8500005",
        "youtube_video_id": "lelN3xUltqU",
        "art": "https://cdn-images.dzcdn.net/images/cover/22fedaf5d2b0ac8977b93bc1db7a4a2a/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Hounds%20Of%20Love%20Kate%20Bush",
            "appleMusic": "https://music.apple.com/us/album/hounds-of-love-2018-remaster/1675560565?i=1675560828&uo=4",
            "deezer": "https://www.deezer.com/track/2173954697",
            "youtube": "https://www.youtube.com/watch?v=lelN3xUltqU",
            "youtubeMusic": "https://music.youtube.com/watch?v=lelN3xUltqU",
        },
    },
    {
        "title": "Beautiful Ones",
        "artist": "The London Suede",
        "album": "Coming up",
        "isrc": "GBL2J1000002",
        "youtube_video_id": "POOHnFD-pec",
        "art": "https://cdn-images.dzcdn.net/images/cover/e51052405a379a72e08366036b39c175/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Beautiful%20Ones%20%28Remastered%29%20The%20London%20Suede",
            "appleMusic": "https://music.apple.com/us/album/beautiful-ones/1535272783?i=1535273597&uo=4",
            "deezer": "https://www.deezer.com/track/1206873902",
            "youtube": "https://www.youtube.com/watch?v=POOHnFD-pec",
            "youtubeMusic": "https://music.youtube.com/watch?v=POOHnFD-pec",
        },
    },
    {
        "title": "Tom's Diner",
        "artist": "DNA",
        "album": "RetroSpective: The Best Of Suzanne Vega",
        "isrc": "USAM19104302",
        "youtube_video_id": "NB1VdkCdIug",
        "art": "https://cdn-images.dzcdn.net/images/cover/e66c8802b4e32613ade556425b07ede8/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Tom%27s%20Diner%20%287%22%20Version%29%20DNA",
            "appleMusic": "https://music.apple.com/us/album/toms-diner-7-a/1443836067?i=1443836345&uo=4",
            "deezer": "https://www.deezer.com/track/549263622",
            "youtube": "https://www.youtube.com/watch?v=NB1VdkCdIug",
            "youtubeMusic": "https://music.youtube.com/watch?v=NB1VdkCdIug",
        },
    },
    {
        "title": "Roygbiv",
        "artist": "Boards Of Canada",
        "album": "Music Has The Right To Children",
        "isrc": "GBBPW9800019",
        "youtube_video_id": "SM4tQcUt_mQ",
        "art": "https://cdn-images.dzcdn.net/images/cover/c3c2e2a739ed501d01791b16a3fd9ad3/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Roygbiv%20Boards%20Of%20Canada",
            "appleMusic": "https://music.apple.com/us/album/roygbiv/281116024?i=281116081&uo=4",
            "deezer": "https://www.deezer.com/track/29373661",
            "youtube": "https://www.youtube.com/watch?v=SM4tQcUt_mQ",
            "youtubeMusic": "https://music.youtube.com/watch?v=SM4tQcUt_mQ",
        },
    },
    {
        "title": "Cissy Strut",
        "artist": "The Meters",
        "album": "Funkify Your Life: The Meters Anthology",
        "isrc": "USRH10125719",
        "youtube_video_id": "Nd3yDoOyvbY",
        "art": "https://cdn-images.dzcdn.net/images/cover/1f323efaf631f075f8e0b1c9279993d6/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Cissy%20Strut%20The%20Meters",
            "appleMusic": "https://music.apple.com/us/album/cissy-strut/59401239?i=59401193&uo=4",
            "deezer": "https://www.deezer.com/track/671183",
            "youtube": "https://www.youtube.com/watch?v=Nd3yDoOyvbY",
            "youtubeMusic": "https://music.youtube.com/watch?v=Nd3yDoOyvbY",
        },
    },
    {
        "title": "Fake Plastic Trees",
        "artist": "Radiohead",
        "album": "The Bends",
        "isrc": "GBAYE9400056",
        "youtube_video_id": "n5h0qHwNrHk",
        "art": "https://cdn-images.dzcdn.net/images/cover/0d2ccaf5f7b35af57f3d9c8f4504a6e6/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Fake%20Plastic%20Trees%20Radiohead",
            "appleMusic": "https://music.apple.com/us/album/fake-plastic-trees/1097862703?i=1097862845&uo=4",
            "deezer": "https://www.deezer.com/track/138544263",
            "youtube": "https://www.youtube.com/watch?v=n5h0qHwNrHk",
            "youtubeMusic": "https://music.youtube.com/watch?v=n5h0qHwNrHk",
        },
    },
    {
        "title": "Sabotage",
        "artist": "Beastie Boys",
        "album": "Solid Gold Hits",
        "isrc": "USCA20501226",
        "youtube_video_id": "z5rRZdiu1UE",
        "art": "https://cdn-images.dzcdn.net/images/cover/fa78eb123d50cb183e6089746364a66b/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Sabotage%20Beastie%20Boys",
            "appleMusic": "https://music.apple.com/us/album/sabotage/724971392?i=724971921&uo=4",
            "deezer": "https://www.deezer.com/track/3119536",
            "youtube": "https://www.youtube.com/watch?v=z5rRZdiu1UE",
            "youtubeMusic": "https://music.youtube.com/watch?v=z5rRZdiu1UE",
        },
    },
    {
        "title": "Only Shallow",
        "artist": "my bloody valentine",
        "album": "Amateur",
        "isrc": "USMTD9509802",
        "youtube_video_id": "nwfCoKNI5hs",
        "art": "https://cdn-images.dzcdn.net/images/cover/765eceaeb557875a0c5b72e26a00f2f9/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Only%20Shallow%20my%20bloody%20valentine",
            "appleMusic": "https://music.apple.com/us/album/only-shallow/1589230434?i=1589230439&uo=4",
            "deezer": "https://www.deezer.com/track/949559",
            "youtube": "https://www.youtube.com/watch?v=nwfCoKNI5hs",
            "youtubeMusic": "https://music.youtube.com/watch?v=nwfCoKNI5hs",
        },
    },
    {
        "title": "Rid Of Me",
        "artist": "PJ Harvey",
        "album": "Rid Of Me",
        "isrc": "GBAAN9300092",
        "youtube_video_id": "8PlaNe3mXl8",
        "art": "https://cdn-images.dzcdn.net/images/cover/6da6a70f9cdd019953ef2c9a524b6a34/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Rid%20Of%20Me%20PJ%20Harvey",
            "appleMusic": "https://music.apple.com/us/album/rid-of-me/1440923277?i=1440923286&uo=4",
            "deezer": "https://www.deezer.com/track/1161109",
            "youtube": "https://www.youtube.com/watch?v=8PlaNe3mXl8",
            "youtubeMusic": "https://music.youtube.com/watch?v=8PlaNe3mXl8",
        },
    },
    {
        "title": "Enjoy the Silence",
        "artist": "Depeche Mode",
        "album": "The Singles 86-98",
        "isrc": "GBAJH9800146",
        "youtube_video_id": "aGSKrC7dGcY",
        "art": "https://cdn-images.dzcdn.net/images/cover/e73716d037ee24f1331a8c0332526590/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Enjoy%20the%20Silence%20Depeche%20Mode",
            "appleMusic": "https://music.apple.com/us/album/enjoy-the-silence/1612543823?i=1612544004&uo=4",
            "deezer": "https://www.deezer.com/track/68515055",
            "youtube": "https://www.youtube.com/watch?v=aGSKrC7dGcY",
            "youtubeMusic": "https://music.youtube.com/watch?v=aGSKrC7dGcY",
        },
    },
    {
        "title": "Ceremony",
        "artist": "New Order",
        "album": "Singles",
        "isrc": "GBAAP1500062",
        "youtube_video_id": "VXLTVvuAfso",
        "art": "https://cdn-images.dzcdn.net/images/cover/197e425f52b7841c402437f34594a7bb/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Ceremony%20%28Version%201%3B%202016%20Remaster%29%20New%20Order",
            "appleMusic": "https://music.apple.com/us/album/ceremony/1530256325?i=1530256507&uo=4",
            "deezer": "https://www.deezer.com/track/131744032",
            "youtube": "https://www.youtube.com/watch?v=VXLTVvuAfso",
            "youtubeMusic": "https://music.youtube.com/watch?v=VXLTVvuAfso",
        },
    },
    {
        "title": "Idioteque",
        "artist": "Radiohead",
        "album": "Kid A",
        "isrc": "GBAYE0000817",
        "youtube_video_id": "q-Nymir3q34",
        "art": "https://cdn-images.dzcdn.net/images/cover/e5925065cdb1cefbc3bd75af4a1f1801/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Idioteque%20Radiohead",
            "appleMusic": "https://music.apple.com/us/album/idioteque-live-in-oxford/1097873905?i=1097874664&uo=4",
            "deezer": "https://www.deezer.com/track/138547601",
            "youtube": "https://www.youtube.com/watch?v=q-Nymir3q34",
            "youtubeMusic": "https://music.youtube.com/watch?v=q-Nymir3q34",
        },
    },
    {
        "title": "Bizarre Love Triangle",
        "artist": "New Order",
        "album": "Brotherhood (Collector's Edition)",
        "isrc": "GBCRL0800398",
        "youtube_video_id": "tkOr12AQpnU",
        "art": "https://cdn-images.dzcdn.net/images/cover/de9f344c076cf9c44d6f5a7572cdd5cd/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/Bizarre%20Love%20Triangle%20New%20Order",
            "appleMusic": "https://music.apple.com/us/album/bizarre-love-triangle/1040972118?i=1040972132&uo=4",
            "deezer": "https://www.deezer.com/track/2481156",
            "youtube": "https://www.youtube.com/watch?v=tkOr12AQpnU",
            "youtubeMusic": "https://music.youtube.com/watch?v=tkOr12AQpnU",
        },
    },
    {
        "title": "A Forest",
        "artist": "The Cure",
        "album": "Seventeen Seconds",
        "isrc": "USEE10500788",
        "youtube_video_id": "xik-y0xlpZ0",
        "art": "https://cdn-images.dzcdn.net/images/cover/95f889f95eaf12538f46a55b65d63801/500x500-000000-80-0-0.jpg",
        "links": {
            "spotify": "https://open.spotify.com/search/A%20Forest%20%282006%20Remaster%29%20The%20Cure",
            "appleMusic": "https://music.apple.com/us/album/a-forest/65619601?i=65619482&uo=4",
            "deezer": "https://www.deezer.com/track/14639134",
            "youtube": "https://www.youtube.com/watch?v=xik-y0xlpZ0",
            "youtubeMusic": "https://music.youtube.com/watch?v=xik-y0xlpZ0",
        },
    },
]

# Source-only picks (MYS-201): no ISRC, identified by the exact page they came
# from. `source_key` formats are enforced by SOURCE_KEY_PATTERN — a YouTube id
# is exactly 11 URL-safe-base64 chars, a Bandcamp key is <artist>/<track> in
# lowercase slugs. Only the originating platform gets a link, which is the whole
# point of the badge.
SOURCE_ONLY = [
    {
        "title": "Ambient Drift",
        "artist": "Hollow Ridge",
        "source_key": "bandcamp:hollowridge/ambient-drift",
        "art": None,
        "links": {"bandcamp": "https://hollowridge.bandcamp.com/track/ambient-drift"},
    },
    {
        "title": "Basement Session No. 4",
        "artist": "Marlow Tapes",
        "source_key": "youtube:dQw4w9WgXcQ",
        "art": None,
        "links": {"youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    },
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


def song_for(mix_number: int, seat: int) -> dict[str, object]:
    """A stable, non-repeating song per (mix, seat) slot."""
    return SONGS[(mix_number * 7 + seat * 3) % len(SONGS)]


def make_submission(mix: Mix, user: User, song: dict[str, object], **kwargs) -> Submission:
    """A catalogue submission carrying the full metadata a real one would.

    Album art and platform links are what make the cards look like the product
    rather than a wireframe; without them every row is a grey box with no
    listen affordance, because PlatformLinks renders nothing when the dict is
    empty.

    youtube_video_id/youtube_lookup_attempted_at are stamped as already
    resolved (MysteryMixClub-t2ai) so pending_submissions_stmt's three-way
    AND (video_id NULL, attempted_at NULL, source_key NULL) excludes every
    seeded catalogue submission from the backfill worker's live-API pass.
    """
    return Submission(
        mix_id=mix.id,
        user_id=user.id,
        isrc=song["isrc"],
        title=song["title"],
        artist=song["artist"],
        album=song["album"],
        album_art_url=song["art"],
        platform_links=song["links"],
        youtube_video_id=song["youtube_video_id"],
        youtube_lookup_attempted_at=NOW,
        **kwargs,
    )


def make_source_submission(mix: Mix, user: User, track: dict[str, object], **kwargs) -> Submission:
    """A source-only submission (MYS-201): a Bandcamp or YouTube pick with no
    catalogue identity at all — no ISRC, and only the one platform it came
    from. Exercises SourceBadge and the "songs that may not be on all
    playlists" notice, neither of which has anything to show otherwise."""
    return Submission(
        mix_id=mix.id,
        user_id=user.id,
        isrc=None,
        source_key=track["source_key"],
        title=track["title"],
        artist=track["artist"],
        album=None,
        album_art_url=track["art"],
        platform_links=track["links"],
        **kwargs,
    )


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
    # Every third mix carries one source-only pick, so the SourceBadge and the
    # "may not be on all playlists" notice have something to show in the
    # archive as well as on the live ballot.
    source_seat = 3 if mix_number % 3 == 0 else None
    subs: list[Submission] = []
    for seat, member in enumerate(members):
        shared = dict(
            participation_mode="vibing" if member is viber else "playing",
            note=RNG.choice([None, "an easy pick this week", "took me a while to land on this"]),
            created_at=opened + timedelta(hours=RNG.randint(1, 40)),
        )
        if seat == source_seat:
            sub = make_source_submission(
                mix, member, SOURCE_ONLY[mix_number % len(SOURCE_ONLY)], **shared
            )
        else:
            sub = make_submission(mix, member, song_for(mix_number, seat), **shared)
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
        # Not one of the eleven: used only as a removed member below.
        departed = await find_or_create_user(session, "quill@example.com", "Quill")

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
            session.add(
                ClubMember(
                    club_id=submitting.id,
                    user_id=member.id,
                    # One member sits the club out in casual mode (MYS-112).
                    # Chosen from the six who have NOT submitted to mix 4, so
                    # their stance actually resolves from membership rather
                    # than being overridden by a submission's own mode.
                    vibe_mode=member is others[7],
                )
            )
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
            # Deliberately a short window (~5h) where the voting club's is 48h,
            # so the two DeadlineChip countdowns read differently side by side.
            submission_deadline=NOW + timedelta(hours=5),
        )
        session.add(m4)
        await session.flush()
        # Six of eleven have submitted so far — Dawn deliberately has NOT, so
        # the submit form is what she lands on.
        for seat, member in enumerate(others[:6]):
            session.add(
                make_submission(
                    m4,
                    member,
                    song_for(4, seat),
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
                    # Dawn is organizer via organizer_id; her own member row
                    # stays "member", which is what the role endpoint expects.
                    # Wren is a CO-ORGANIZER (MYS-99): role="admin" grants full
                    # operational parity everywhere _load_club_as_organizer
                    # gates, so signing in as wren@example.com is how you test
                    # the co-organizer path against a club you don't own.
                    role="admin" if member is others[2] else "member",
                )
            )
        # A departed member: their own user, NOT one of the eleven, because
        # (club_id, user_id) is unique — reusing an active member would just
        # collide. Keeps the active count at 11 while giving the roster and the
        # rejoin path a genuine removed case.
        session.add(
            ClubMember(
                club_id=voting.id,
                user_id=departed.id,
                role="member",
                removed_at=NOW - timedelta(days=30),
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
            shared = dict(
                participation_mode="playing",
                note=None if seat % 3 else "curious what everyone makes of this one",
                created_at=sub_opened + timedelta(hours=seat * 2),
            )
            # Seat 5 is a Bandcamp-only pick, so the live ballot carries a
            # SourceBadge and trips the "may not be on all playlists" notice.
            if seat == 5:
                sub = make_source_submission(m11, member, SOURCE_ONLY[0], **shared)
            else:
                sub = make_submission(m11, member, song_for(11, seat), **shared)
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

        # Notes on the LIVE ballot, not just the archive. Notes can be left
        # while voting is open (they stay hidden until the reveal), so without
        # these the notes affordance on a votable card has nothing behind it.
        # None are Dawn's, so the "leave a note" composer is what she gets.
        for seat in (0, 2, 4, 7):
            target = ballot[seat]
            for author in RNG.sample([m for m in others if m.id != target.user_id], 2):
                session.add(
                    Note(
                        mix_id=m11.id,
                        author_id=author.id,
                        submission_id=target.id,
                        body=RNG.choice(NOTE_BODIES),
                    )
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

        # Waitlist entries so the admin console's waitlist panel and the
        # signup-trend chart have something to render. A mix of invited and
        # still-waiting, since the panel distinguishes them.
        await session.execute(delete(WaitlistEntry))
        for i, email in enumerate(
            [
                "arlo@example.com",
                "beatrix@example.com",
                "casimir@example.com",
                "delphine@example.com",
                "emory@example.com",
                "fenwick@example.com",
            ]
        ):
            session.add(
                WaitlistEntry(
                    email=email,
                    created_at=NOW - timedelta(days=14 - i * 2),
                    # The first two have been let in already.
                    invited_at=(NOW - timedelta(days=3)) if i < 2 else None,
                    invited_by=dawn.id if i < 2 else None,
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
