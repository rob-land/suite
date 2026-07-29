"""Core media value types shared across the suite shells.

Moved from couch (2026-07-29) so couch, zoetrope, and hearth drive
one provider layer.

Dataclasses, no logic. Keep these provider-agnostic so the UI never
inspects provider-specific shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import StereoHint


class ContentType(str, Enum):
    MOVIE = "movie"
    SHOW = "show"
    SEASON = "season"
    EPISODE = "episode"
    MUSIC_ALBUM = "music_album"
    MUSIC_TRACK = "music_track"
    MUSIC_ARTIST = "music_artist"
    PODCAST = "podcast"
    PODCAST_EPISODE = "podcast_episode"
    OTHER = "other"


class Capability(str, Enum):
    MOVIES = "movies"
    TV = "tv"
    MUSIC = "music"
    PODCASTS = "podcasts"
    LIVE_TV = "live_tv"
    SEARCH = "search"
    RECOMMENDATIONS = "recommendations"
    WATCHLIST = "watchlist"
    RESUME = "resume"


class ContentRating(str, Enum):
    """Approximate cross-system rating ordered by strictness."""
    G = "G"
    TV_Y = "TV-Y"
    TV_Y7 = "TV-Y7"
    TV_G = "TV-G"
    PG = "PG"
    TV_PG = "TV-PG"
    PG_13 = "PG-13"
    TV_14 = "TV-14"
    R = "R"
    TV_MA = "TV-MA"
    NC_17 = "NC-17"
    UNRATED = "UNRATED"


# Ordering used for kid-mode comparisons. Lower index == more permissive
# for kids.
_RATING_ORDER = [
    ContentRating.G, ContentRating.TV_Y, ContentRating.TV_Y7,
    ContentRating.TV_G, ContentRating.PG, ContentRating.TV_PG,
    ContentRating.PG_13, ContentRating.TV_14,
    ContentRating.R, ContentRating.TV_MA, ContentRating.NC_17,
]


def rating_at_or_below(rating: ContentRating | None,
                       cap: ContentRating) -> bool:
    """True if ``rating`` is allowed by the kid-mode ``cap``."""
    if rating is None:
        return False  # fail-closed for missing rating
    if rating is ContentRating.UNRATED:
        return False
    try:
        return _RATING_ORDER.index(rating) <= _RATING_ORDER.index(cap)
    except ValueError:
        return False


@dataclass(slots=True)
class StreamInfo:
    """How to play a particular item: URL plus any extra mpv hints."""
    url: str
    mime_type: str | None = None
    mpv_options: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    # When True, mpv should be told to resume from `start_offset` seconds.
    start_offset: float = 0.0
    # Stereo-3D hint for players configured for 3D output (zoetrope);
    # 2D players simply ignore it.
    stereo: StereoHint = field(default_factory=StereoHint.mono)


@dataclass(slots=True)
class MediaItem:
    """A single thing the user might watch / listen to.

    Provider-agnostic. ``provider_id`` and ``provider_item_id`` together
    uniquely identify the source row; ``canonical_id`` (TMDB/TVDB/etc)
    powers cross-source dedup.
    """
    provider_id: str
    provider_item_id: str
    title: str
    content_type: ContentType
    description: str = ""
    year: int | None = None
    runtime_seconds: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    rating: ContentRating | None = None
    canonical_id: str | None = None  # e.g. "tmdb:12345"
    # For shows: parent show id. For episodes: also season/episode index.
    parent_id: str | None = None
    season_index: int | None = None
    episode_index: int | None = None
    # Resume position; None if never started.
    progress_seconds: float | None = None
    # 0..1; used when the item is "watched" but not 100% complete.
    progress_fraction: float | None = None
    # Genre / tag list for badging on detail / discovery rails.
    genres: list[str] = field(default_factory=list)
    # Stereoscopic-3D hint in the suite-wide vocabulary (suite_providers):
    # format + how it was learned (server tag / filename / probe). Mono
    # default keeps non-3D providers untouched.
    stereo: StereoHint = field(default_factory=StereoHint.mono)
    # Chapter list for skip-intro and chapter-skip navigation. Each
    # entry is {"name": str, "start_seconds": float}. Optional.
    chapters: list[dict[str, Any]] = field(default_factory=list)
    # Provider-specific extra data passed back when the user picks the item.
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Unique key within the local UI."""
        return f"{self.provider_id}:{self.provider_item_id}"

    @property
    def dedup_key(self) -> str:
        """Key used for cross-provider dedup."""
        return self.canonical_id or self.key


@dataclass(slots=True)
class AuthStatus:
    """Result of an authentication attempt."""
    ok: bool
    message: str = ""
    # Optional updated credential blob to persist back into the profile.
    credentials: dict[str, Any] | None = None


@dataclass(slots=True)
class SourceConfig:
    """Persisted configuration for a single configured source instance."""
    id: str            # local UUID; e.g. "jellyfin-home"
    provider: str      # provider class id; e.g. "jellyfin"
    display_name: str
    # Per-source config (server URL, etc). Auth lives per-profile.
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
