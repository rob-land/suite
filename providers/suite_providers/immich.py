"""Immich provider (stub).

Stereo capability: PROBE_REQUIRED, with useful API pre-filters
(surveyed 2026-07-28):

- MPO: ingested (since ~2026-04, PR #27963) but registered as
  image/jpeg "web-unsupported" — previews show only the first (left)
  frame; no stereo flag on assets. Pre-filter: ``POST
  /api/search/metadata`` with an ``originalFileName`` substring match
  for ``.mpo``.
- Apple spatial HEIC: indistinguishable from 2D HEIC in the API (the
  spatial-detection and WebXR-viewer PRs #18055/#18099 died unmerged).
- VR180 photos: ``exifInfo.projectionType == "EQUIRECTANGULAR"`` flags
  immersive-ness but NOT stereo-vs-mono (no GImage right-eye XMP, no
  st3d indexing).
- The guarantee that makes stereo viable anyway: originals are never
  modified and ``GET /api/assets/{id}/original`` returns byte-exact
  files — so the client parses MPO second frames / HEIC stereo groups /
  GImage XMP itself via :meth:`original_bytes` (zoetrope's gallery
  already carries the MPO parser).

Strategy: cheap API pre-filter (filename + projectionType) → download
original → authoritative client-side stereo parse → cache verdict
keyed on asset id + checksum.
"""
from __future__ import annotations

from .models import StereoCapability
from .provider import PhotoLibrary


class ImmichPhotoLibrary(PhotoLibrary):
    id = "immich"
    stereo_capability = StereoCapability.PROBE_REQUIRED

    def __init__(self, base_url: str, api_key: str):
        raise NotImplementedError(
            "pending implementation (API-key auth, timeline/search "
            "endpoints, original download, stereo verdict cache)")

    def ping(self) -> bool:  # pragma: no cover - stub
        raise NotImplementedError

    def photos(self):  # pragma: no cover - stub
        raise NotImplementedError
