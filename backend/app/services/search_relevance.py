"""Shared relevance scoring for song search candidates (MYS-175).

Each provider integration (Deezer search, Apple's iTunes lookup, YouTube's Data
API lookup) independently searches by free-text title/artist and, left
unranked, is prone to surfacing covers/karaoke/live versions above the
original recording, or an unrelated top hit entirely. This module gives all
three a single, consistent way to rank candidates against the query and
demote non-original versions — the "cheap wins" MYS-175 calls out.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import TypeVar

T = TypeVar("T")

# Version markers that suggest a candidate isn't the original studio
# recording the user searched for. Checked against the candidate title only.
_JUNK_MARKERS = (
    "karaoke",
    "live",
    "cover",
    "tribute",
    "originally performed by",
    "instrumental",
    "remix",
    "re-recorded",
    "rerecorded",
)

# Multiplicative penalty applied when a candidate carries a junk marker the
# query didn't ask for. A penalty rather than a hard exclusion, so a track
# that genuinely only exists as a live recording can still surface.
_JUNK_PENALTY = 0.5


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_junk_marker(text: str) -> bool:
    normalized = _normalize(text)
    return any(marker in normalized for marker in _JUNK_MARKERS)


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def score(
    query_title: str,
    query_artist: str | None,
    candidate_title: str,
    candidate_artist: str | None,
) -> float:
    """Score a candidate's relevance to the query. Higher is better.

    Title similarity dominates (0.7 weight); artist similarity is a
    tiebreaker (0.3) and is skipped when either side has no artist. Candidates
    whose title carries a version marker the query didn't ask for
    (karaoke/live/cover/...) are penalized rather than excluded.
    """
    title_score = _similarity(query_title, candidate_title)
    if query_artist and candidate_artist:
        artist_score = _similarity(query_artist, candidate_artist)
        combined = 0.7 * title_score + 0.3 * artist_score
    else:
        combined = title_score

    if not _has_junk_marker(query_title) and _has_junk_marker(candidate_title):
        combined *= _JUNK_PENALTY

    return combined


def rank(
    query_title: str,
    query_artist: str | None,
    candidates: list[T],
    *,
    title_of: Callable[[T], str],
    artist_of: Callable[[T], str | None],
) -> list[T]:
    """Return ``candidates`` sorted best-match-first. Stable on ties."""
    scored = [
        (score(query_title, query_artist, title_of(c), artist_of(c)), i, c)
        for i, c in enumerate(candidates)
    ]
    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    return [c for _, _, c in scored]


def best_match(
    query_title: str,
    query_artist: str | None,
    candidates: list[T],
    *,
    title_of: Callable[[T], str],
    artist_of: Callable[[T], str | None],
) -> T | None:
    """Return the single best-matching candidate, or ``None`` if empty."""
    ranked = rank(query_title, query_artist, candidates, title_of=title_of, artist_of=artist_of)
    return ranked[0] if ranked else None
