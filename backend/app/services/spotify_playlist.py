"""Pure helpers for building a Spotify playlist's metadata from a mix (MYS-83).

No network, no DB — trivially unit-tested, mirroring :mod:`youtube_playlist`.
"""

from __future__ import annotations

# Spotify silently truncates over-long names/descriptions; keep them tidy.
_MAX_NAME = 100
_MAX_DESCRIPTION = 300


def playlist_name(club_name: str, mix_number: int, theme: str | None) -> str:
    """Human title for the saved playlist, e.g.
    ``MysteryMixClub: Friday Mixtape, Late Summer Feels``.

    Includes the **club name** (MYS-86) so titles are unique per club. Falls back
    to ``Mix N`` when the mystery mix has no theme yet — the full phrase would
    double the brand ("MysteryMixClub: …, Mystery Mix 3").

    The name is display-only: playlist reuse keys on the stored playlist ID
    (MYS-89), not this string, so renaming is safe and titles need only be
    human-distinct, not machine-unique. (An earlier name-keyed reuse scheme,
    MYS-87, was replaced; this docstring previously described it.)
    """
    club = club_name.strip() or "MysteryMixClub"
    suffix = theme.strip() if theme and theme.strip() else f"Mix {mix_number}"
    return f"MysteryMixClub: {club}, {suffix}"[:_MAX_NAME]


def playlist_description(club_name: str, mix_number: int, theme: str | None) -> str:
    """Short description stored on the playlist."""
    club = club_name.strip() or "MysteryMixClub"
    if theme and theme.strip():
        text = (
            f"Every song from Mystery Mix {mix_number} ({theme.strip()}) "
            f"of {club} on MysteryMixClub."
        )
    else:
        text = f"Every song from Mystery Mix {mix_number} of {club} on MysteryMixClub."
    return text[:_MAX_DESCRIPTION]
