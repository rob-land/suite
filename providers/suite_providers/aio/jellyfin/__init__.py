"""Jellyfin source provider package.

The original `providers/jellyfin.py` was an 894-line single-class
file. JellyfinProvider is now assembled here from feature mixins
(`_http`, `_auth`, `_items`, `_listings`, `_matching`, `_playback`).
External callers still `from ..providers.jellyfin import JellyfinProvider`.
"""

from .jellyfin import JellyfinProvider

__all__ = ["JellyfinProvider"]
from .discovery import DiscoveredServer, discover  # noqa: E402

__all__ = ["JellyfinProvider", "DiscoveredServer", "discover"]
