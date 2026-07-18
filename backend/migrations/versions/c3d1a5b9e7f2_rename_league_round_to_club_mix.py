"""rename league/round schema to club/mix (MYS-196 cutover)

Every statement is a metadata-only rename (ACCESS EXCLUSIVE for milliseconds,
no table rewrite, no data movement); Alembic runs the whole revision in one
transaction, so it applies atomically or not at all. Postgres does NOT rename
constraints/indexes when their table or column is renamed, so every name that
embeds the old vocabulary is renamed explicitly — target names match what a
fresh SQLAlchemy create_all of the post-rename models generates, keeping
metadata and live schema identical.

Names below were enumerated from the live schema (pg_constraint/pg_indexes),
not assumed. ck_league_members_role is deliberately NOT renamed — the model
keeps that constraint name until the R3/R4 identifier cleanup.

Revision ID: c3d1a5b9e7f2
Revises: ad64945262e3
Create Date: 2026-07-18
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c3d1a5b9e7f2"
down_revision: Union[str, Sequence[str], None] = "ad64945262e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old, new) — applied in order for upgrade, reversed for downgrade.
_TABLES = [
    ("leagues", "clubs"),
    ("league_members", "club_members"),
    ("rounds", "mixes"),
    ("spotify_round_playlists", "spotify_mix_playlists"),
    ("apple_round_playlists", "apple_mix_playlists"),
]

# (table_after_upgrade, old_col, new_col)
_COLUMNS = [
    ("clubs", "total_rounds", "total_mixes"),
    ("clubs", "current_round", "current_mix"),
    ("club_members", "league_id", "club_id"),
    ("invites", "league_id", "club_id"),
    ("mixes", "league_id", "club_id"),
    ("mixes", "round_number", "mix_number"),
    ("submissions", "round_id", "mix_id"),
    ("votes", "round_id", "mix_id"),
    ("notes", "round_id", "mix_id"),
    ("spotify_mix_playlists", "round_id", "mix_id"),
    ("apple_mix_playlists", "round_id", "mix_id"),
]

# (table_after_upgrade, old_constraint, new_constraint) — PKs, FKs, UQs.
_CONSTRAINTS = [
    # primary keys
    ("clubs", "leagues_pkey", "clubs_pkey"),
    ("club_members", "league_members_pkey", "club_members_pkey"),
    ("mixes", "rounds_pkey", "mixes_pkey"),
    ("spotify_mix_playlists", "spotify_round_playlists_pkey", "spotify_mix_playlists_pkey"),
    ("apple_mix_playlists", "apple_round_playlists_pkey", "apple_mix_playlists_pkey"),
    # foreign keys
    ("clubs", "leagues_organizer_id_fkey", "clubs_organizer_id_fkey"),
    ("club_members", "league_members_league_id_fkey", "club_members_club_id_fkey"),
    ("club_members", "league_members_user_id_fkey", "club_members_user_id_fkey"),
    ("invites", "invites_league_id_fkey", "invites_club_id_fkey"),
    ("mixes", "rounds_league_id_fkey", "mixes_club_id_fkey"),
    ("submissions", "submissions_round_id_fkey", "submissions_mix_id_fkey"),
    ("votes", "votes_round_id_fkey", "votes_mix_id_fkey"),
    ("notes", "notes_round_id_fkey", "notes_mix_id_fkey"),
    (
        "spotify_mix_playlists",
        "spotify_round_playlists_round_id_fkey",
        "spotify_mix_playlists_mix_id_fkey",
    ),
    (
        "spotify_mix_playlists",
        "spotify_round_playlists_user_id_fkey",
        "spotify_mix_playlists_user_id_fkey",
    ),
    (
        "apple_mix_playlists",
        "apple_round_playlists_round_id_fkey",
        "apple_mix_playlists_mix_id_fkey",
    ),
    (
        "apple_mix_playlists",
        "apple_round_playlists_user_id_fkey",
        "apple_mix_playlists_user_id_fkey",
    ),
    # unique constraints (renaming the constraint renames its backing index)
    ("club_members", "uq_league_members_league_user", "uq_club_members_club_user"),
    ("mixes", "uq_rounds_league_number", "uq_mixes_club_number"),
    (
        "spotify_mix_playlists",
        "uq_spotify_round_playlists_round_user",
        "uq_spotify_mix_playlists_mix_user",
    ),
    (
        "apple_mix_playlists",
        "uq_apple_round_playlists_round_user",
        "uq_apple_mix_playlists_mix_user",
    ),
]

# (old_index, new_index) — plain indexes; ALTER INDEX is table-agnostic.
_INDEXES = [
    ("ix_leagues_organizer_id", "ix_clubs_organizer_id"),
    ("ix_league_members_league_id", "ix_club_members_club_id"),
    ("ix_league_members_user_id", "ix_club_members_user_id"),
    ("ix_invites_league_id", "ix_invites_club_id"),
    ("ix_rounds_league_id", "ix_mixes_club_id"),
    ("ix_submissions_round_id", "ix_submissions_mix_id"),
    ("ix_votes_round_id", "ix_votes_mix_id"),
    ("ix_notes_round_id", "ix_notes_mix_id"),
    ("ix_spotify_round_playlists_round_id", "ix_spotify_mix_playlists_mix_id"),
    ("ix_spotify_round_playlists_user_id", "ix_spotify_mix_playlists_user_id"),
    ("ix_apple_round_playlists_round_id", "ix_apple_mix_playlists_mix_id"),
    ("ix_apple_round_playlists_user_id", "ix_apple_mix_playlists_user_id"),
]


def upgrade() -> None:
    for old, new in _TABLES:
        op.rename_table(old, new)
    for table, old, new in _COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    for table, old, new in _CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old, new in _INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")


def downgrade() -> None:
    for old, new in reversed(_INDEXES):
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for table, old, new in reversed(_CONSTRAINTS):
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for table, old, new in reversed(_COLUMNS):
        op.alter_column(table, new, new_column_name=old)
    for old, new in reversed(_TABLES):
        op.rename_table(new, old)
