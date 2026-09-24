"""Free-text content filter (MysteryMixClub-4vii.43) -- App Store Guideline 1.2
requires "a mechanism to filter objectionable material", not just after-the-fact
reporting (4vii.13) and blocking (4vii.42).

Design (ADR 0036): a curated denylist checked at WRITE time on every
member-visible free-text surface. Normalizing the candidate (accents off,
leetspeak mapped, repeated letters collapsed, tokenized on non-alphanumerics)
closes the common first-order evasions; matching on WHOLE normalized tokens
deliberately avoids Scunthorpe-family false positives ("bass", "class",
"assassin", "Scunthorpe" all pass).

The tier here is hate/harassment — slurs, sexual-violence and explicit sexual
terms, targeted-harassment phrases. Generic profanity ("fuck", "shit") is
intentionally allowed: it is the speech register of this app's actual users,
and it isn't what 1.2's "objectionable content" prong targets (an abusive
environment is). ADR 0036's revisit-if covers tightening that.

Rejection raises a 422 with one generic message — the flagged term is never
echoed back (that would teach evaders exactly which normalization to route
around).
"""

import re
import unicodedata

from fastapi import HTTPException, status

#: The single user-facing rejection message. Generic on purpose (see module
#: docstring); surfaced verbatim by the frontend's readErrorMessage.
CONTENT_POLICY_MESSAGE = "that text isn't allowed here — try something else."

# Common leetspeak/homoglyph substitutions mapped back to their letter. Kept to
# unambiguous look-alikes; anything cleverer than this is accepted as an
# evasion hole (ADR 0036).
_LEET = str.maketrans(
    {
        "0": "o",
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "8": "b",
        "@": "a",
        "$": "s",
        "€": "e",
        "£": "l",
        "ß": "b",
        "а": "a",  # Cyrillic look-alikes that survive into latin text
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
    }
)

_REPEAT_RUN = re.compile(r"(.)\1+")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
# A run of single-letter tokens is the dotted/spaced-out evasion ("r.e.t.a.r.d",
# "r e t a r d"): join it and check the joined form too. Safe because the join
# only matches when it spells an exact denylist term — "i a m c o o l" joins to
# "iamcool", which matches nothing.

# Curated denylist. Singular/stem forms only where pluralization is the plain
# +s (handled by matching, not by listing every inflection); entries with
# spaces are matched as token sequences.
_DENYLIST: tuple[str, ...] = (
    # Racial / ethnic / religious slurs (and their primary respellings).
    "nigger",
    "nigga",
    "beaner",
    "chink",
    "gook",
    "kike",
    "spic",
    "wetback",
    "coon",
    "paki",
    "raghead",
    "towelhead",
    "zipperhead",
    "darky",
    "darkey",
    "gringo",  # mild, but reads as abuse in context-poor short text
    # Homophobic / transphobic slurs.
    "faggot",
    "faggots",
    "fag",
    "fags",
    "dyke",
    "dykes",
    "tranny",
    "trannies",
    "shemale",
    "cocksucker",
    # Ableist slurs.
    "retard",
    "retards",
    "retarded",
    "spaz",
    "spastic",
    "mongoloid",
    # Sexual violence / exploitation.
    "rape",
    "raping",
    "rapist",
    "molest",
    "molester",
    "pedo",
    "pedophile",
    "paedophile",
    "cp",
    "jailbait",
    "groomer",
    "grooming",
    # Explicit sexual terms (pornographic register, not club banter).
    "cunt",
    "cunts",
    "pussy",
    "clit",
    "bukkake",
    "cumshot",
    "cumshots",
    # Targeted harassment phrases — the classics a reviewer looks for.
    "kill yourself",
    "kys",
    "go die",
)


# Pluralization handling without listing every form: a token matches when it
# equals the term or is the term + s/es.
def _normalize(raw: str) -> list[str]:
    """Lowercase, strip accents, map leetspeak, collapse repeated letters,
    split into tokens."""
    decomposed = unicodedata.normalize("NFKD", raw)
    asciiish = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = asciiish.lower().translate(_LEET)
    collapsed = _REPEAT_RUN.sub(r"\1", lowered)
    return [t for t in _TOKEN_SPLIT.split(collapsed) if t]


def _token_matches(token: str, term: str) -> bool:
    return token == term or token == term + "s" or token == term + "es"


# Pre-normalize the denylist itself through the same pipeline (the run-collapse
# matters here: "kill" must compare against an already-collapsed "kil"). Kept
# as (original, normalized-words) pairs so a hit can report the readable term.
_NORMALIZED_DENYLIST: list[tuple[str, list[str]]] = [(term, _normalize(term)) for term in _DENYLIST]


def find_denied_term(value: str) -> str | None:
    """Return the first flagged denylist entry in `value`, or None.

    Word-exact on normalized tokens (plus plain +s/+es plurals); multi-word
    entries match consecutive tokens. Exposed for tests; routes use
    `reject_if_flagged`.
    """
    tokens = _normalize(value)
    token_set = set(tokens)
    single_word_terms = [(t, w) for t, w in _NORMALIZED_DENYLIST if len(w) == 1]
    for original, words in _NORMALIZED_DENYLIST:
        if len(words) > 1:
            for i in range(len(tokens) - len(words) + 1):
                if all(_token_matches(tokens[i + j], w) for j, w in enumerate(words)):
                    return original
        else:
            if any(_token_matches(t, words[0]) for t in token_set):
                return original
    if len(tokens) > 1 and all(len(t) == 1 for t in tokens):
        joined = "".join(tokens)
        for original, words in single_word_terms:
            if _token_matches(joined, words[0]):
                return original
    return None


def reject_if_flagged(value: str | None) -> None:
    """Raise 422 if `value` trips the denylist. No-op on None/empty."""
    if value and find_denied_term(value) is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=CONTENT_POLICY_MESSAGE,
        )
