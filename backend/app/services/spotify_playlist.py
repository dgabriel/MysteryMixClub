"""Pure helpers for building a Spotify playlist's metadata from a round (MYS-83).

No network, no DB — trivially unit-tested, mirroring :mod:`youtube_playlist`.
"""

from __future__ import annotations

# Spotify silently truncates over-long names/descriptions; keep them tidy.
_MAX_NAME = 100
_MAX_DESCRIPTION = 300


def playlist_name(round_number: int, theme: str | None) -> str:
    """Human title for the saved playlist, e.g. ``MysteryMixClub — Round 3: Late
    Summer Feels`` (falls back to ``Round N`` when the round has no theme yet)."""
    label = f"Round {round_number}"
    if theme and theme.strip():
        label = f"{label}: {theme.strip()}"
    return f"MysteryMixClub — {label}"[:_MAX_NAME]


def playlist_description(round_number: int, theme: str | None) -> str:
    """Short description stored on the playlist."""
    if theme and theme.strip():
        text = f"The full mix from Round {round_number} ({theme.strip()}) on MysteryMixClub."
    else:
        text = f"The full mix from Round {round_number} on MysteryMixClub."
    return text[:_MAX_DESCRIPTION]
