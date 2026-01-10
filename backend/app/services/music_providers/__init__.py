"""
Music search providers package.
Supports multiple music search APIs with a pluggable architecture.
"""
from .base import MusicSearchProvider
from .itunes import ITunesSearchProvider
# from .spotify import SpotifySearchProvider  # Uncomment when implemented
# from .deezer import DeezerSearchProvider    # Uncomment when implemented

__all__ = [
    'MusicSearchProvider',
    'ITunesSearchProvider',
]
