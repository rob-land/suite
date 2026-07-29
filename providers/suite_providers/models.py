"""Shared data models for suite media providers.

The stereo vocabulary matches stereoscope's probe slugs so a provider
hint, a filename inference, and a byte-level probe all speak one
language (see beampro/docs/16-suite-design-language.md §provider model).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class StereoFormat(enum.Enum):
    """How a piece of media packs its stereo views (if any)."""

    MONO = "mono"
    SBS_FULL = "sbs-full"
    SBS_HALF = "sbs-half"
    TAB_FULL = "tab-full"
    TAB_HALF = "tab-half"
    MVC = "mvc"
    MVHEVC = "mvhevc"
    MPO = "mpo"                # stereo photo pair in one JPEG container
    STEREO_PAIR = "pair"       # explicit L/R files or in-file pair (HEIC)
    UNKNOWN = "unknown"

    @property
    def is_stereo(self) -> bool:
        return self not in (StereoFormat.MONO, StereoFormat.UNKNOWN)


class StereoConfidence(enum.Enum):
    """How the stereo hint was obtained — clients decide whether to
    trust it or re-probe. Ordered weakest → strongest."""

    NONE = "none"              # no signal; assume mono until probed
    NAME = "name"              # inferred from filename/path conventions
    SERVER = "server"          # the backend stores/serves a 3D field
    PROBED = "probed"          # byte-level detection (stereoscope/libmvc/
                               # MPO parse) — authoritative


@dataclass(frozen=True)
class StereoHint:
    format: StereoFormat = StereoFormat.UNKNOWN
    confidence: StereoConfidence = StereoConfidence.NONE

    @classmethod
    def mono(cls) -> "StereoHint":
        return cls(StereoFormat.MONO, StereoConfidence.NONE)


class StereoCapability(enum.Enum):
    """What a *backend* can tell clients about stereo content — declared
    per provider so UIs never promise 3D they can't verify."""

    SERVER_TAGGED = "server-tagged"    # queryable 3D field (best)
    NAME_INFERRED = "name-inferred"    # filenames via API; client applies rules
    PROBE_REQUIRED = "probe-required"  # only the bytes know


class ResumeKind(enum.Enum):
    """Android TV Watch Next semantics — the shared first rail."""

    CONTINUE = "continue"      # partially watched; carries progress
    NEXT = "next"              # next episode in a started series
    WATCHLIST = "watchlist"    # user-added
    NEW = "new"                # newly available in a followed context


@dataclass(frozen=True)
class MediaSource:
    """Where the bytes live. `path` for local providers, `url` for
    network ones; both may be set (url preferred for streaming, path
    for probing)."""

    provider_id: str
    item_id: str
    path: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class VideoItem:
    source: MediaSource
    title: str
    year: int | None = None
    duration_s: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    stereo: StereoHint = field(default_factory=StereoHint)
    rating: str | None = None          # certification, for kid-mode
    series: str | None = None
    season: int | None = None
    episode: int | None = None


@dataclass(frozen=True)
class PhotoItem:
    source: MediaSource
    title: str
    taken_at: str | None = None        # ISO 8601
    thumb_url: str | None = None
    stereo: StereoHint = field(default_factory=StereoHint)
    right_source: MediaSource | None = None   # explicit L/R pair


@dataclass(frozen=True)
class ResumeEntry:
    kind: ResumeKind
    item: VideoItem
    position_s: int | None = None      # CONTINUE only
    engaged_at: str | None = None      # ISO 8601; recency ordering
