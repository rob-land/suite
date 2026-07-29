"""Abstract MediaProvider interface.

Every backend (Jellyfin, Spotify, YouTube, …) implements this. Methods
are async — providers do network I/O on the shared asyncio loop.

The shell never talks to a provider directly; it goes through
``SourceManager`` / ``ContentAggregator``. Providers don't know about
each other.
"""

from __future__ import annotations

import abc
from typing import Any

from ..media import (
    AuthStatus,
    Capability,
    ContentType,
    MediaItem,
    SourceConfig,
    StreamInfo,
)


class ProviderError(Exception):
    """Base for provider failures the shell should surface to the user."""


class ProviderAuthError(ProviderError):
    """Credentials missing, expired, or rejected by the backend."""


class ProviderUnreachableError(ProviderError):
    """Network or server error reaching the backend."""


class MediaProvider(abc.ABC):
    """One backend that produces ``MediaItem``s.

    Implementations are stateless across instances — per-instance
    config (server URL, API key, etc.) is passed via ``configure``.
    Per-profile credentials are passed in via the ``credentials`` arg
    on each call so a single provider can serve multiple profiles
    without globals.
    """

    #: Stable identifier shared across all instances of this provider type.
    provider_id: str = ""

    #: Human-readable name for the "Add Source" gallery.
    display_name: str = ""

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.source_id: str = ""
        self.source_display_name: str = ""

    def configure(self, source: SourceConfig) -> None:
        """Apply a ``SourceConfig`` to this instance."""
        self.source_id = source.id
        self.source_display_name = source.display_name or self.display_name
        self.config = dict(source.config)

    @abc.abstractmethod
    def get_capabilities(self) -> set[Capability]:
        """What kinds of UI surfaces this provider contributes to."""

    @abc.abstractmethod
    async def authenticate(
        self, credentials: dict[str, Any] | None,
    ) -> AuthStatus:
        """Verify (and possibly refresh) ``credentials``.

        Returning ``AuthStatus(ok=True, credentials=...)`` lets the
        provider hand back updated tokens to persist.
        """

    @abc.abstractmethod
    async def search(
        self, query: str, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
    ) -> list[MediaItem]:
        """Free-text search across the backend."""

    @abc.abstractmethod
    async def list_library(
        self, content_type: ContentType,
        credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 60,
    ) -> list[MediaItem]:
        """Library list for a content type. Sorted by recency or relevance."""

    @abc.abstractmethod
    async def get_continue_watching(
        self, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 12,
    ) -> list[MediaItem]:
        """Items the user has started but not finished."""

    @abc.abstractmethod
    async def get_stream_url(
        self, item: MediaItem, credentials: dict[str, Any] | None,
    ) -> StreamInfo:
        """Resolve the playable URL for ``item``."""

    @abc.abstractmethod
    async def report_progress(
        self, item: MediaItem, position_seconds: float,
        credentials: dict[str, Any] | None,
        completed: bool = False,
    ) -> None:
        """Push playback position back to the backend."""

    # --- Optional hooks ------------------------------------------------

    async def get_episodes(
        self, show: MediaItem, credentials: dict[str, Any] | None,
    ) -> list[MediaItem]:
        """Episode list for a show. Default: empty (movies only)."""
        return []

    async def get_recommendations(
        self, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 12,
    ) -> list[MediaItem]:
        """Backend-side recommendations. Default: empty."""
        return []

    async def set_watched(
        self, item: MediaItem, watched: bool,
        credentials: dict[str, Any] | None,
    ) -> None:
        """Mark/unmark an item as watched. Default: no-op."""
        return None

    async def get_next_episode(
        self, item: MediaItem, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        """Episode that follows ``item`` in the same show.

        ``item`` is expected to be an EPISODE; default returns None
        (no auto-play next on this provider).
        """
        return None

    async def get_recently_added(
        self, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 24,
    ) -> list[MediaItem]:
        """Items added to the user's libraries recently. Default: empty."""
        return []

    async def get_similar(
        self, item: MediaItem, credentials: dict[str, Any] | None,
        limit: int = 12,
    ) -> list[MediaItem]:
        """Items similar to ``item``. Default: empty."""
        return []

    async def find_by_canonical_id(
        self, canonical_id: str, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        """Look up a single item by canonical_id (e.g. ``tmdb:12345``).

        Returns the local MediaItem if this source has it, else None.
        Default: no result. Used for cross-source dedup and the
        availability indicator on TMDB-only tiles.
        """
        return None

    async def completed_items(
        self, credentials: dict[str, Any] | None,
        limit: int = 200,
    ) -> list[MediaItem]:
        """Items the user has finished. Used for taste clustering."""
        return []

    async def list_by_genre(
        self, genre: str, content_type: ContentType,
        credentials: dict[str, Any] | None,
        limit: int = 24,
    ) -> list[MediaItem]:
        """Library list filtered by a single genre. Default empty."""
        return []

    async def next_up_for(
        self, show: MediaItem, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        """Next-to-watch episode for ``show``. Default None."""
        return None

    async def close(self) -> None:
        """Release any pooled clients. Default: no-op."""
        return None

    def invalidate_caches(self) -> None:
        """Drop any locally-cached state (e.g. library index) so the
        next query forces a fresh fetch. Default: no-op."""
        return None
