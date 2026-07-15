"""Unit tests for app.services.search_relevance (MYS-175)."""

from app.services.search_relevance import best_match, rank, score


def _title_of(item: dict) -> str:
    return item["title"]


def _artist_of(item: dict) -> str | None:
    return item.get("artist")


def test_exact_title_and_artist_scores_highest():
    exact = score("Storm II", "GENER8ION", "Storm II", "GENER8ION")
    unrelated = score("Storm II", "GENER8ION", "Totally Different Song", "Someone Else")
    assert exact > unrelated


def test_karaoke_version_penalized_when_not_requested():
    original = score("American Pie", "Don McLean", "American Pie", "Don McLean")
    karaoke = score("American Pie", "Don McLean", "American Pie (Karaoke Version)", "Karaoke Kings")
    assert original > karaoke


def test_junk_marker_not_penalized_when_query_asks_for_it():
    # If the user explicitly searches for a live version, don't punish it.
    live_score = score("Song Title (Live)", None, "Song Title (Live)", None)
    plain_score = score("Song Title (Live)", None, "Song Title", None)
    assert live_score >= plain_score


def test_rank_orders_best_match_first():
    candidates = [
        {"title": "Totally Different Song", "artist": "Someone Else"},
        {"title": "Storm II", "artist": "GENER8ION"},
    ]
    ranked = rank("Storm II", "GENER8ION", candidates, title_of=_title_of, artist_of=_artist_of)
    assert ranked[0]["title"] == "Storm II"


def test_rank_is_stable_on_ties():
    candidates = [{"title": "Song A"}, {"title": "Song B"}]
    ranked = rank("nothing like either", None, candidates, title_of=_title_of, artist_of=_artist_of)
    assert [c["title"] for c in ranked] == ["Song A", "Song B"]


def test_best_match_returns_none_for_empty_list():
    assert best_match("x", None, [], title_of=_title_of, artist_of=_artist_of) is None


def test_best_match_returns_only_candidate_regardless_of_score():
    candidates = [{"title": "Completely Unrelated"}]
    chosen = best_match(
        "Storm II", "GENER8ION", candidates, title_of=_title_of, artist_of=_artist_of
    )
    assert chosen == candidates[0]


def test_artist_mismatch_lowers_score_as_tiebreaker():
    same_artist = score("Song", "Real Artist", "Song", "Real Artist")
    diff_artist = score("Song", "Real Artist", "Song", "Cover Band")
    assert same_artist > diff_artist
