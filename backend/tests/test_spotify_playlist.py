"""Unit tests for app.services.spotify_playlist (MYS-83/86/87) — pure helpers."""

from app.services.spotify_playlist import playlist_description, playlist_name


def test_name_includes_league_and_theme():
    # League name (MYS-86) makes the title unique per league so playlists can be
    # reused rather than duplicated (MYS-87).
    assert (
        playlist_name("Friday Mixtape", 3, "Late Summer Feels")
        == "MysteryMixClub: Friday Mixtape, Late Summer Feels"
    )


def test_name_without_theme_falls_back_to_round_number():
    assert playlist_name("Friday Mixtape", 2, None) == "MysteryMixClub: Friday Mixtape, Round 2"
    assert playlist_name("Friday Mixtape", 2, "   ") == "MysteryMixClub: Friday Mixtape, Round 2"


def test_name_is_capped_at_100_chars():
    assert len(playlist_name("L", 1, "x" * 200)) == 100


def test_description_mentions_league_theme_and_round():
    desc = playlist_description("Friday Mixtape", 3, "Late Summer Feels")
    assert "Round 3" in desc
    assert "Late Summer Feels" in desc
    assert "Friday Mixtape" in desc


def test_description_without_theme():
    desc = playlist_description("Friday Mixtape", 4, None)
    assert "Round 4" in desc
    assert "Friday Mixtape" in desc
    assert "(" not in desc  # no empty parenthetical


def test_description_is_capped():
    assert len(playlist_description("L", 1, "x" * 500)) == 300
