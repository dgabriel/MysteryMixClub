"""Pure helpers for building a Spotify playlist's metadata from a round (MYS-83).

No network, no DB — trivially unit-tested, mirroring :mod:`youtube_playlist`.
"""

from __future__ import annotations

# Spotify silently truncates over-long names/descriptions; keep them tidy.
_MAX_NAME = 100
_MAX_DESCRIPTION = 300


def playlist_name(league_name: str, round_number: int, theme: str | None) -> str:
    """Human title for the saved playlist, e.g.
    ``MysteryMixClub: Friday Mixtape, Late Summer Feels``.

    Includes the **league name** (MYS-86) so titles are unique per league, which
    is also what lets us **reuse** a same-named playlist instead of creating a
    duplicate (MYS-87). Falls back to ``Round N`` when the round has no theme yet.

    NOTE: playlist reuse keys on this exact name, so it must be stable and unique
    per round. It relies on a round's theme being distinct within its league (the
    normal case); a blank theme uses the unique ``Round N`` instead.
    """
    league = league_name.strip() or "MysteryMixClub"
    suffix = theme.strip() if theme and theme.strip() else f"Round {round_number}"
    return f"MysteryMixClub: {league}, {suffix}"[:_MAX_NAME]


def playlist_description(league_name: str, round_number: int, theme: str | None) -> str:
    """Short description stored on the playlist."""
    league = league_name.strip() or "MysteryMixClub"
    if theme and theme.strip():
        text = (
            f"The full mix from Round {round_number} ({theme.strip()}) "
            f"of {league} on MysteryMixClub."
        )
    else:
        text = f"The full mix from Round {round_number} of {league} on MysteryMixClub."
    return text[:_MAX_DESCRIPTION]
