"""Abstract provider interfaces, organized by media kind.

Extraction target: couch's ``MediaProvider`` (Jellyfin reference impl)
migrates here; zoetrope and hearth consume the same interfaces. All
methods are synchronous in the scaffold — couch's async httpx layer maps
1:1 when the implementations move over.
"""
from __future__ import annotations

import abc
from collections.abc import Iterator

from .models import (
    PhotoItem,
    ResumeEntry,
    StereoCapability,
    VideoItem,
)


class Provider(abc.ABC):
    """Base: identity + capability declaration + kid-mode obligation."""

    #: stable id, e.g. "jellyfin", "immich", "local"
    id: str = "abstract"
    #: what this backend can tell clients about stereo content
    stereo_capability: StereoCapability = StereoCapability.PROBE_REQUIRED

    @abc.abstractmethod
    def ping(self) -> bool:
        """Cheap health check."""

    def apply_rating_cap(self, cap: str | None) -> None:
        """Kid-mode: providers filter server-side where possible; the
        default remembers the cap for client-side filtering."""
        self._rating_cap = cap


class VideoLibrary(Provider):
    """Movies/shows source (Jellyfin, Plex, local files)."""

    @abc.abstractmethod
    def videos(self) -> Iterator[VideoItem]:
        """All playable titles visible to the active profile."""

    @abc.abstractmethod
    def resume_rail(self) -> list[ResumeEntry]:
        """Watch Next semantics: CONTINUE/NEXT/WATCHLIST/NEW, ordered by
        recency. Empty when the backend has no state."""

    def report_progress(self, item: VideoItem, position_s: int) -> None:
        """Push playback position back (no-op where unsupported)."""


class PhotoLibrary(Provider):
    """Stills source (Immich, local folders)."""

    @abc.abstractmethod
    def photos(self) -> Iterator[PhotoItem]:
        """All photos visible to the active profile, newest first."""

    def original_bytes(self, item: PhotoItem) -> bytes | None:
        """The untouched original file (needed to parse MPO second
        frames / HEIC stereo pairs client-side). None when the backend
        can't serve originals — stereo display is then impossible."""
        return None
