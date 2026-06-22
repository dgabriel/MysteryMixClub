"""Unit tests for app.services.spotify_playlist (MYS-83) — pure helpers."""

from app.services.spotify_playlist import playlist_description, playlist_name


def test_name_with_theme():
    assert playlist_name(3, "Late Summer Feels") == "MysteryMixClub — Round 3: Late Summer Feels"


def test_name_without_theme_falls_back_to_round_number():
    assert playlist_name(2, None) == "MysteryMixClub — Round 2"
    assert playlist_name(2, "   ") == "MysteryMixClub — Round 2"


def test_name_is_capped_at_100_chars():
    assert len(playlist_name(1, "x" * 200)) == 100


def test_description_mentions_theme_and_round():
    desc = playlist_description(3, "Late Summer Feels")
    assert "Round 3" in desc
    assert "Late Summer Feels" in desc


def test_description_without_theme():
    desc = playlist_description(4, None)
    assert "Round 4" in desc
    assert "(" not in desc  # no empty parenthetical


def test_description_is_capped():
    assert len(playlist_description(1, "x" * 500)) == 300
