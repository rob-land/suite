"""suite_providers — shared media-backend abstraction for the suite
(zoetrope · couch · hearth).

Design: beampro/docs/16-suite-design-language.md §"The provider model".
Network providers (jellyfin, plex, immich) are scaffolded stubs pending
extraction from couch and the 3D-capability survey; localfiles is the
working reference implementation.
"""
from .models import (
    MediaSource,
    PhotoItem,
    ResumeEntry,
    ResumeKind,
    StereoCapability,
    StereoConfidence,
    StereoFormat,
    StereoHint,
    VideoItem,
)
from .media import (
    AuthStatus,
    Capability,
    ContentRating,
    ContentType,
    MediaItem,
    SourceConfig,
    StreamInfo,
    rating_at_or_below,
)
from .provider import PhotoLibrary, Provider, VideoLibrary

__all__ = [
    "MediaSource",
    "PhotoItem",
    "PhotoLibrary",
    "Provider",
    "ResumeEntry",
    "ResumeKind",
    "StereoCapability",
    "StereoConfidence",
    "StereoFormat",
    "StereoHint",
    "VideoItem",
    "VideoLibrary",
    "AuthStatus",
    "Capability",
    "ContentRating",
    "ContentType",
    "MediaItem",
    "SourceConfig",
    "StreamInfo",
    "rating_at_or_below",
]

__version__ = "0.2.0"
