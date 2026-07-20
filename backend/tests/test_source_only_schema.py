"""Schema-level tests for the source-only submission identity (MYS-201).

Exercises the ``submissions`` table shape the migration
``f2a9c4b7e1d8_submissions_source_only`` establishes (and which
``Base.metadata.create_all`` reproduces for the test DB):

* ``isrc`` is nullable and ``source_key`` is nullable, but
* the ``ck_submissions_isrc_or_source`` CHECK guarantees at least one is set.

Insert paths: isrc-only OK, source_key-only OK, both OK, neither → rejected.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.club import Club
from app.models.club_member import ClubMember
from app.models.mix import Mix
from app.models.submission import Submission
from app.models.user import User


async def _seed_mix(db_session) -> tuple[User, Mix]:
    user = User(email="s@example.com", display_name="S")
    db_session.add(user)
    await db_session.flush()
    club = Club(name="L", organizer_id=user.id, total_mixes=3, votes_per_player=3)
    db_session.add(club)
    await db_session.flush()
    db_session.add(ClubMember(club_id=club.id, user_id=user.id))
    mix_ = Mix(club_id=club.id, mix_number=1, theme="t", state="open_submission")
    db_session.add(mix_)
    await db_session.commit()
    await db_session.refresh(mix_)
    await db_session.refresh(user)
    return user, mix_


async def test_isrc_only_insert_is_allowed(db_session):
    user, mix_ = await _seed_mix(db_session)
    db_session.add(
        Submission(
            mix_id=mix_.id,
            user_id=user.id,
            isrc="USABC1234567",
            source_key=None,
            title="song",
            artist="A",
        )
    )
    await db_session.commit()  # no CHECK violation


async def test_source_key_only_insert_is_allowed(db_session):
    user, mix_ = await _seed_mix(db_session)
    db_session.add(
        Submission(
            mix_id=mix_.id,
            user_id=user.id,
            isrc=None,
            source_key="bandcamp:coolband/song-title",
            title="song",
            artist="A",
        )
    )
    await db_session.commit()  # no CHECK violation


async def test_both_isrc_and_source_key_insert_is_allowed_by_the_db(db_session):
    # The DB CHECK only guarantees *at least one* identity; the "exactly one" rule
    # is the submit endpoint's model validator, not a DB constraint.
    user, mix_ = await _seed_mix(db_session)
    db_session.add(
        Submission(
            mix_id=mix_.id,
            user_id=user.id,
            isrc="USABC1234567",
            source_key="youtube:PRpiBpDy7MQ",
            title="song",
            artist="A",
        )
    )
    await db_session.commit()  # no CHECK violation


async def test_neither_isrc_nor_source_key_is_rejected(db_session):
    user, mix_ = await _seed_mix(db_session)
    db_session.add(
        Submission(
            mix_id=mix_.id,
            user_id=user.id,
            isrc=None,
            source_key=None,
            title="song",
            artist="A",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
