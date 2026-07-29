"""Jellyfin provider (stub — implementation migrates from couch).

Stereo capability: SERVER_TAGGED — the only video backend with a real
queryable 3D model (surveyed 2026-07-28):

- ``BaseItemDto.Video3DFormat`` ∈ {HalfSideBySide, FullSideBySide,
  HalfTopAndBottom, FullTopAndBottom, MVC}; populated unconditionally on
  every Video item (no ``fields=`` opt-in) and also on MediaSourceInfo.
- Set from FILENAME tokens only (Emby.Naming Format3DParser): standalone
  ``fsbs/hsbs/sbs/ftab/htab/tab/sbs3d/mvc`` or ``3d``+``sbs/hsbs/tab/htab``
  pairs; bare ``sbs``/``tab`` map to HALF. One container-level case:
  Matroska StereoMode=1 (ffprobe ``stereo_mode=left_right``) →
  FullSideBySide. No MVC-in-MKV sniffing; no MV-HEVC value exists.
- ``/Items?is3D=true`` filters server-side (boolean only — filter
  specific packings client-side on Video3DFormat).
- The field is user-editable via the item-update API, so misnamed files
  can be fixed without renames.
- Consequence for ripsaw: emit Kodi/Jellyfin-compatible names
  (``Title (Year) 3D.HSBS.mkv`` satisfies both rule sets) AND set
  Matroska StereoMode on outputs.

Map DTO → suite via :func:`suite_providers.naming.jellyfin_format_to_stereo`.
MV-HEVC files scan as plain HEVC → clients must probe (PROBE fallback).
"""
from __future__ import annotations

from .models import StereoCapability
from .provider import VideoLibrary


class JellyfinVideoLibrary(VideoLibrary):
    id = "jellyfin"
    stereo_capability = StereoCapability.SERVER_TAGGED

    def __init__(self, base_url: str, token: str):
        raise NotImplementedError(
            "pending extraction of couch's Jellyfin MediaProvider "
            "(auth incl. Quick Connect, /Items, resume/progress)")

    def ping(self) -> bool:  # pragma: no cover - stub
        raise NotImplementedError

    def videos(self):  # pragma: no cover - stub
        raise NotImplementedError

    def resume_rail(self):  # pragma: no cover - stub
        raise NotImplementedError
