"""add ON DELETE behavior to the remaining users FK columns (MysteryMixClub-4vii.38)

Eight FK columns referencing ``users.id`` had no ON DELETE at all, so
hard-deleting a user with a row in any of them raised an IntegrityError --
confirmed for SpotifyConnection, and the scheduled purge runs its whole batch
in one transaction, so a single such account rolled back the entire night's
purge. See ``app/jobs/purge_accounts.py`` and each model's own comment for the
reasoning behind CASCADE vs SET NULL per table.

Existing constraint names aren't assumed -- this looks up whatever the live
constraint is actually called before dropping and recreating it, rather than
guessing Postgres's default `<table>_<column>_fkey` shape. In this repo that
guess happens to still be right for all eight (the club/mix rename migration,
c3d1a5b9e7f2, explicitly renamed each constraint along with its table), but a
dynamic lookup doesn't depend on that having been done consistently, and costs
nothing extra.

`downgrade()` restores each column's ORIGINAL constraint name exactly (not a
throwaway name), and that isn't just tidiness: c3d1a5b9e7f2's own downgrade
renames apple_mix_playlists_user_id_fkey / spotify_mix_playlists_user_id_fkey
back to their round-era names, by that exact literal string, so a downgrade
chain that runs this migration's downgrade before reaching c3d1a5b9e7f2's
needs the original name to genuinely be there when it does (CI's full
migration round-trip caught this the first time this file left a `_plain`
placeholder name instead).

Downgrading after any of the SET NULL columns has actually gone NULL (a
report whose reporter or reported member was purged, an invite/waitlist row
whose referenced user was purged) will fail loudly at the final
`alter_column(nullable=False)` calls below -- a real NULL can't satisfy a
NOT NULL constraint. That failure rolls back atomically with the rest of this
migration's downgrade (nothing partial is left behind); clearing or backfilling
those rows first is the caller's job if a downgrade is ever genuinely needed.

Additive in effect (loosens a constraint / adds cleanup on delete) but not a
purely additive DDL op -- it's still safe against a live database: no data is
read, moved, or dropped, only a constraint is swapped for an equivalent one
with ON DELETE behavior added, plus two columns becoming nullable (a widening
change, never rejects existing data).

Revision ID: f1a8c3e9b6d4
Revises: 8b3d5e7a9c21
Create Date: 2026-09-22 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a8c3e9b6d4"
down_revision: Union[str, Sequence[str], None] = "8b3d5e7a9c21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, ON DELETE action, new constraint name, ORIGINAL constraint
# name -- confirmed against each column's own create/rename migration, not
# guessed: apple_mix_playlists/spotify_mix_playlists via c3d1a5b9e7f2's rename
# (their round-era names' successors), waitlist_entries/invites via their own
# explicit `name=` at creation (42875937489b, 9b4a7e2c5d81), the rest via
# Postgres's default `<table>_<column>_fkey` from their unnamed
# ForeignKeyConstraint at creation (f4b9d7c2a1e8, 80ab60c9ee7b, 59fe3246660c).
_TARGETS = [
    (
        "apple_mix_playlists",
        "user_id",
        "CASCADE",
        "fk_apple_mix_playlists_user_id_users",
        "apple_mix_playlists_user_id_fkey",
    ),
    (
        "spotify_connections",
        "user_id",
        "CASCADE",
        "fk_spotify_connections_user_id_users",
        "spotify_connections_user_id_fkey",
    ),
    (
        "spotify_mix_playlists",
        "user_id",
        "CASCADE",
        "fk_spotify_mix_playlists_user_id_users",
        "spotify_mix_playlists_user_id_fkey",
    ),
    (
        "oauth_exchange_codes",
        "user_id",
        "CASCADE",
        "fk_oauth_exchange_codes_user_id_users",
        "oauth_exchange_codes_user_id_fkey",
    ),
    (
        "waitlist_entries",
        "invited_by",
        "SET NULL",
        "fk_waitlist_entries_invited_by_users",
        "fk_waitlist_entries_invited_by",
    ),
    (
        "invites",
        "used_by_user_id",
        "SET NULL",
        "fk_invites_used_by_user_id_users",
        "fk_invites_used_by_user_id_users",
    ),
    (
        "reports",
        "reporter_id",
        "SET NULL",
        "fk_reports_reporter_id_users",
        "reports_reporter_id_fkey",
    ),
    (
        "reports",
        "reported_user_id",
        "SET NULL",
        "fk_reports_reported_user_id_users",
        "reports_reported_user_id_fkey",
    ),
]


def _swap_fk(table: str, column: str, ondelete: str, new_name: str) -> None:
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys(table):
        if fk["referred_table"] == "users" and fk["constrained_columns"] == [column]:
            # Reflection types this as str | None, but an actual live
            # constraint always has a name (Postgres assigns one even when
            # unnamed at creation) -- this loop only ever sees real, existing
            # constraints from the inspector.
            assert fk["name"] is not None
            op.drop_constraint(fk["name"], table, type_="foreignkey")
            break
    op.create_foreign_key(new_name, table, "users", [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    # Widen first: SET NULL needs a nullable column, and these two are
    # currently NOT NULL (a report always named both parties until now).
    op.alter_column("reports", "reporter_id", nullable=True)
    op.alter_column("reports", "reported_user_id", nullable=True)

    for table, column, ondelete, new_name, _original_name in _TARGETS:
        _swap_fk(table, column, ondelete, new_name)


def downgrade() -> None:
    for table, column, _ondelete, new_name, original_name in _TARGETS:
        op.drop_constraint(new_name, table, type_="foreignkey")
        op.create_foreign_key(original_name, table, "users", [column], ["id"])

    op.alter_column("reports", "reporter_id", nullable=False)
    op.alter_column("reports", "reported_user_id", nullable=False)
