"""Add multi-song support

Revision ID: 005
Revises: 004
Create Date: 2026-01-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add songs_per_round to leagues table
    op.add_column('leagues', sa.Column('songs_per_round', sa.Integer(), nullable=False, server_default='1'))

    # 2. Create songs table
    op.create_table(
        'songs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('submission_id', sa.Integer(), nullable=False),
        sa.Column('song_title', sa.String(200), nullable=False),
        sa.Column('artist_name', sa.String(200), nullable=False),
        sa.Column('album_name', sa.String(200), nullable=True),
        sa.Column('songlink_url', sa.String(500), nullable=False),
        sa.Column('spotify_url', sa.String(500), nullable=True),
        sa.Column('apple_music_url', sa.String(500), nullable=True),
        sa.Column('youtube_url', sa.String(500), nullable=True),
        sa.Column('amazon_music_url', sa.String(500), nullable=True),
        sa.Column('tidal_url', sa.String(500), nullable=True),
        sa.Column('youtube_music_url', sa.String(500), nullable=True),
        sa.Column('deezer_url', sa.String(500), nullable=True),
        sa.Column('artwork_url', sa.String(500), nullable=True),
        sa.Column('order', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True),
        sa.ForeignKeyConstraint(['submission_id'], ['submissions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_songs_id'), 'songs', ['id'], unique=False)

    # 3. Migrate existing submission data to songs table
    # Get all existing submissions with their song data
    connection = op.get_bind()
    submissions = connection.execute(
        sa.text("""
            SELECT id, song_title, artist_name, album_name, songlink_url,
                   spotify_url, apple_music_url, youtube_url, artwork_url
            FROM submissions
        """)
    ).fetchall()

    # Create one song record for each existing submission
    for submission in submissions:
        connection.execute(
            sa.text("""
                INSERT INTO songs
                (submission_id, song_title, artist_name, album_name, songlink_url,
                 spotify_url, apple_music_url, youtube_url, artwork_url, `order`)
                VALUES
                (:submission_id, :song_title, :artist_name, :album_name, :songlink_url,
                 :spotify_url, :apple_music_url, :youtube_url, :artwork_url, 1)
            """),
            {
                'submission_id': submission[0],
                'song_title': submission[1],
                'artist_name': submission[2],
                'album_name': submission[3],
                'songlink_url': submission[4],
                'spotify_url': submission[5],
                'apple_music_url': submission[6],
                'youtube_url': submission[7],
                'artwork_url': submission[8]
            }
        )

    # 4. Add song_id column to votes table (temporarily nullable)
    op.add_column('votes', sa.Column('song_id', sa.Integer(), nullable=True))

    # 5. Update votes to reference songs instead of submissions
    # For each vote, find the song that belongs to the voted submission
    connection.execute(
        sa.text("""
            UPDATE votes v
            INNER JOIN songs s ON s.submission_id = v.submission_id
            SET v.song_id = s.id
        """)
    )

    # 6. Make song_id non-nullable and add foreign key
    op.alter_column('votes', 'song_id',
                    existing_type=sa.Integer(),
                    nullable=False)
    op.create_foreign_key('fk_votes_song_id', 'votes', 'songs', ['song_id'], ['id'])

    # 7. Drop old submission_id column from votes
    op.drop_constraint('votes_ibfk_3', 'votes', type_='foreignkey')
    op.drop_column('votes', 'submission_id')

    # 8. Drop old song columns from submissions table
    op.drop_column('submissions', 'song_title')
    op.drop_column('submissions', 'artist_name')
    op.drop_column('submissions', 'album_name')
    op.drop_column('submissions', 'songlink_url')
    op.drop_column('submissions', 'spotify_url')
    op.drop_column('submissions', 'apple_music_url')
    op.drop_column('submissions', 'youtube_url')
    op.drop_column('submissions', 'artwork_url')


def downgrade() -> None:
    # Re-add song columns to submissions
    op.add_column('submissions', sa.Column('artwork_url', sa.String(500), nullable=True))
    op.add_column('submissions', sa.Column('youtube_url', sa.String(500), nullable=True))
    op.add_column('submissions', sa.Column('apple_music_url', sa.String(500), nullable=True))
    op.add_column('submissions', sa.Column('spotify_url', sa.String(500), nullable=True))
    op.add_column('submissions', sa.Column('songlink_url', sa.String(500), nullable=True))
    op.add_column('submissions', sa.Column('album_name', sa.String(200), nullable=True))
    op.add_column('submissions', sa.Column('artist_name', sa.String(200), nullable=True))
    op.add_column('submissions', sa.Column('song_title', sa.String(200), nullable=True))

    # Re-add submission_id to votes
    op.add_column('votes', sa.Column('submission_id', sa.Integer(), nullable=True))

    # Copy song data back to submissions and update votes
    connection = op.get_bind()
    connection.execute(
        sa.text("""
            UPDATE submissions sub
            INNER JOIN songs s ON s.submission_id = sub.id AND s.order = 1
            SET sub.song_title = s.song_title,
                sub.artist_name = s.artist_name,
                sub.album_name = s.album_name,
                sub.songlink_url = s.songlink_url,
                sub.spotify_url = s.spotify_url,
                sub.apple_music_url = s.apple_music_url,
                sub.youtube_url = s.youtube_url,
                sub.artwork_url = s.artwork_url
        """)
    )

    connection.execute(
        sa.text("""
            UPDATE votes v
            INNER JOIN songs s ON s.id = v.song_id
            SET v.submission_id = s.submission_id
        """)
    )

    # Make submission_id non-nullable
    op.alter_column('votes', 'submission_id',
                    existing_type=sa.Integer(),
                    nullable=False)
    op.create_foreign_key('votes_ibfk_3', 'votes', 'submissions', ['submission_id'], ['id'])

    # Drop song_id from votes
    op.drop_constraint('fk_votes_song_id', 'votes', type_='foreignkey')
    op.drop_column('votes', 'song_id')

    # Drop songs table
    op.drop_index(op.f('ix_songs_id'), table_name='songs')
    op.drop_table('songs')

    # Drop songs_per_round from leagues
    op.drop_column('leagues', 'songs_per_round')

    # Make song columns non-nullable again
    op.alter_column('submissions', 'song_title',
                    existing_type=sa.String(200),
                    nullable=False)
    op.alter_column('submissions', 'artist_name',
                    existing_type=sa.String(200),
                    nullable=False)
    op.alter_column('submissions', 'songlink_url',
                    existing_type=sa.String(500),
                    nullable=False)
