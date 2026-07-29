"""JellyfinProvider — host class composing the mixin-split sub-modules.

The original `providers/jellyfin.py` packed the entire Jellyfin
client surface into a single class; this file holds only the
plumbing slots (``__init__``, ``server_url``, ``get_capabilities``,
``invalidate_caches``) and assembles the feature mixins via plain
multiple inheritance.

Endpoints used:
- POST /Users/AuthenticateByName        — username/password auth
- POST /QuickConnect/Initiate           — start Quick Connect (preferred)
- GET  /QuickConnect/Connect            — poll Quick Connect state
- POST /Users/AuthenticateWithQuickConnect
- GET  /Users/{userId}/Items            — library + search
- GET  /Users/{userId}/Items/Resume     — continue watching
- GET  /Items/{itemId}/PlaybackInfo     — stream details
- POST /Sessions/Playing                — start playback session
- POST /Sessions/Playing/Progress       — progress ping
- POST /Sessions/Playing/Stopped        — stop session
"""

from __future__ import annotations

import logging

import httpx

from ...media import Capability
from ..base import MediaProvider, ProviderError
from ._auth import AuthMixin
from ._http import HttpMixin
from ._items import ItemsMixin
from ._listings import ListingsMixin
from ._matching import MatchingMixin
from ._playback import PlaybackMixin

log = logging.getLogger(__name__)


class JellyfinProvider(
    HttpMixin,
    AuthMixin,
    ItemsMixin,
    ListingsMixin,
    MatchingMixin,
    PlaybackMixin,
    MediaProvider,
):
    provider_id = "jellyfin"
    display_name = "Jellyfin"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None

    @property
    def server_url(self) -> str:
        url = self.config.get("server_url", "").rstrip("/")
        if not url:
            raise ProviderError("Jellyfin server URL is not configured")
        return url

    def get_capabilities(self) -> set[Capability]:
        return {
            Capability.MOVIES, Capability.TV, Capability.MUSIC,
            Capability.SEARCH, Capability.RESUME,
        }

    def invalidate_caches(self) -> None:
        # Drop the library-id index so the next availability probe
        # rebuilds it. Doesn't touch the auth state or http client.
        self.__dict__.pop("_index_cache", None)
