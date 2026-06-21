"""Anonymous YouTube playlist link builder (MYS-78).

YouTube's ``watch_videos`` endpoint plays an ad-hoc, ordered list of video ids
without an account or saved playlist:

    https://www.youtube.com/watch_videos?video_ids=ID1,ID2,...

This module assembles that link from the ids resolved per submission at playlist
time. It is pure (no network, no DB) so it is trivially unit-tested.
"""

from __future__ import annotations

from urllib.parse import urlencode

_WATCH_VIDEOS_URL = "https://www.youtube.com/watch_videos"
# watch_videos silently truncates very long lists; cap to keep the URL usable.
_MAX_VIDEOS = 50


def normalize_video_ids(video_ids: list[str]) -> list[str]:
    """The exact ids that go into the link: non-empty, de-duped (first-seen
    order preserved), capped at 50. Callers use this so a track count and the
    URL never disagree."""
    seen: set[str] = set()
    ordered: list[str] = []
    for vid in video_ids:
        if vid and vid not in seen:
            seen.add(vid)
            ordered.append(vid)
            if len(ordered) >= _MAX_VIDEOS:
                break
    return ordered


def build_watch_videos_url(video_ids: list[str]) -> str | None:
    """Build a ``watch_videos`` URL from ordered video ids, or ``None`` if empty.

    De-dupes while preserving first-seen order and caps the list at 50.
    """
    ordered = normalize_video_ids(video_ids)
    if not ordered:
        return None
    query = urlencode({"video_ids": ",".join(ordered)})
    return f"{_WATCH_VIDEOS_URL}?{query}"
