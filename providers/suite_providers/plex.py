"""Plex provider (stub).

Stereo capability: NAME_INFERRED — Plex has NO 3D metadata anywhere
(surveyed 2026-07-28):

- No 3d/stereo attribute on Media/Part/Stream in the API; the scanner
  ignores ``H-SBS``-style filename tokens; deep analysis does not surface
  Matroska StereoMode or frame-packing SEI.
- Escape hatch: ``<Part file="...">`` carries the full server-side path —
  fetch it and apply :func:`suite_providers.naming.video_stereo_hint`
  (the historical third-party Samsung client did exactly this).
- MVC: the server cannot decode it (plays the 2D base view); NEVER allow
  the server to transcode a 3D item — transcoding SBS/TAB mangles the
  stereo since Plex treats it as 2D. Direct-play/download only, then
  probe client-side.
"""
from __future__ import annotations

from .models import StereoCapability
from .provider import VideoLibrary


class PlexVideoLibrary(VideoLibrary):
    id = "plex"
    stereo_capability = StereoCapability.NAME_INFERRED

    def __init__(self, base_url: str, token: str):
        raise NotImplementedError(
            "pending implementation (PIN auth, /library/sections, "
            "Part.file name inference, direct-play-only for stereo)")

    def ping(self) -> bool:  # pragma: no cover - stub
        raise NotImplementedError

    def videos(self):  # pragma: no cover - stub
        raise NotImplementedError

    def resume_rail(self):  # pragma: no cover - stub
        raise NotImplementedError
