"""Source-only track identity helpers (MYS-201).

A *source-only* submission has no ISRC — the track exists only on Bandcamp or
YouTube, not on the ISRC-indexed catalogs (Deezer/Apple/Spotify). Instead of an
ISRC it is identified by an exact ``source_key``:

    youtube:<11-char video id>
    bandcamp:<artist-slug>/<track-slug>

The key is an *exact* reference to the page the submitter chose — it is never
fuzzy-matched. Both the stored key and the URLs reconstructed from it therefore
point at exactly that page: gaps (a platform with no link) are acceptable, a
wrong song is not.
"""

from __future__ import annotations

import re
from typing import Literal

Source = Literal["youtube", "bandcamp"]

# YouTube video ids are exactly 11 URL-safe-base64 chars (an 8-byte value). The
# Bandcamp key is ``<artist>/<track>``; each slug is lowercase alphanumerics and
# hyphens with no leading hyphen — matching Bandcamp subdomains and track paths.
_YOUTUBE_ID = r"[A-Za-z0-9_-]{11}"
_BANDCAMP_SLUG = r"[a-z0-9][a-z0-9-]*"
SOURCE_KEY_PATTERN = rf"^(?:youtube:{_YOUTUBE_ID}|bandcamp:{_BANDCAMP_SLUG}/{_BANDCAMP_SLUG})$"

_YOUTUBE_KEY = re.compile(rf"^youtube:({_YOUTUBE_ID})$")
_BANDCAMP_KEY = re.compile(rf"^bandcamp:({_BANDCAMP_SLUG})/({_BANDCAMP_SLUG})$")


def source_url_for(source_key: str) -> tuple[Source, str]:
    """Return the ``(source, exact_url)`` a ``source_key`` reconstructs to.

    Raises ``ValueError`` on a malformed key. Callers only ever persist keys that
    passed :data:`SOURCE_KEY_PATTERN` validation, so this never fires in practice
    — it guards against a hand-corrupted row rather than user input.
    """
    match = _YOUTUBE_KEY.match(source_key)
    if match:
        return "youtube", f"https://www.youtube.com/watch?v={match.group(1)}"
    match = _BANDCAMP_KEY.match(source_key)
    if match:
        return "bandcamp", f"https://{match.group(1)}.bandcamp.com/track/{match.group(2)}"
    raise ValueError(f"malformed source_key: {source_key!r}")


def source_fields(source_key: str | None) -> tuple[Source | None, str | None]:
    """``(source, source_url)`` for a response model, or ``(None, None)`` for a
    normal ISRC-backed catalog submission (``source_key`` is ``None``)."""
    if not source_key:
        return None, None
    return source_url_for(source_key)


def youtube_video_id_from_key(source_key: str) -> str | None:
    """The bare 11-char video id inside a ``youtube:<id>`` key, else ``None``."""
    match = _YOUTUBE_KEY.match(source_key)
    return match.group(1) if match else None
