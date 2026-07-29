"""Jellyfin video provider.

Stereo capability: SERVER_TAGGED — the only video backend with a real
queryable 3D model (surveyed 2026-07-28): ``Video3DFormat`` ∈
{HalfSideBySide, FullSideBySide, HalfTopAndBottom, FullTopAndBottom,
MVC} is populated on every Video DTO (filename-driven via Emby.Naming;
bare ``sbs``/``tab`` map to HALF; Matroska StereoMode=1 → FullSBS is the
sole container detection; no MV-HEVC value exists — clients probe those).
When the server field is absent we fall back to filename inference on
the DTO ``Path``.

Auth flows (password, Quick Connect) live in the shells' UI (couch's
implementation); this provider takes ready credentials:
``server_url`` + ``access_token`` + ``user_id``. HTTP is synchronous
httpx (the ``network`` extra); shells wrap calls in their own executors.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from .models import (
    MediaSource,
    ResumeEntry,
    ResumeKind,
    StereoCapability,
    StereoConfidence,
    VideoItem,
)
from .naming import jellyfin_format_to_stereo, video_stereo_hint
from .provider import VideoLibrary

_FIELDS = "Path,ProductionYear,RunTimeTicks,OfficialRating,Video3DFormat"
_PAGE = 200
_TICKS_PER_S = 10_000_000


class JellyfinVideoLibrary(VideoLibrary):
    id = "jellyfin"
    stereo_capability = StereoCapability.SERVER_TAGGED

    def __init__(self, server_url: str, access_token: str, user_id: str,
                 client_name: str = "suite", device_id: str = "suite-0"):
        import httpx  # optional dep: suite-providers[network]

        self.user_id = user_id
        auth = (f'MediaBrowser Client="{client_name}", Device="{client_name}", '
                f'DeviceId="{device_id}", Version="0.1", Token="{access_token}"')
        self._http = httpx.Client(
            base_url=server_url.rstrip("/"),
            headers={"X-Emby-Authorization": auth, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0, connect=5.0),
            follow_redirects=True,
        )

    # -- plumbing ------------------------------------------------------------

    def _get(self, path: str, **params: Any) -> dict:
        r = self._http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def _item(self, dto: dict) -> VideoItem:
        stereo = jellyfin_format_to_stereo(dto.get("Video3DFormat"))
        if stereo.confidence is not StereoConfidence.SERVER or not stereo.format.is_stereo:
            named = video_stereo_hint(dto.get("Path") or "")
            if named.format.is_stereo:
                stereo = named
        ticks = dto.get("RunTimeTicks")
        item_id = dto["Id"]
        return VideoItem(
            source=MediaSource(
                self.id, item_id,
                url=f"{self._http.base_url}/Videos/{item_id}/stream?static=true"),
            title=dto.get("Name", "?"),
            year=dto.get("ProductionYear"),
            duration_s=int(ticks / _TICKS_PER_S) if ticks else None,
            poster_url=f"{self._http.base_url}/Items/{item_id}/Images/Primary",
            stereo=stereo,
            rating=dto.get("OfficialRating"),
            series=dto.get("SeriesName"),
            season=dto.get("ParentIndexNumber"),
            episode=dto.get("IndexNumber"),
        )

    # -- VideoLibrary --------------------------------------------------------

    def ping(self) -> bool:
        try:
            return "Id" in self._get("/System/Info/Public")
        except Exception:
            return False

    def videos(self) -> Iterator[VideoItem]:
        start = 0
        while True:
            data = self._get(
                f"/Users/{self.user_id}/Items",
                IncludeItemTypes="Movie,Episode", Recursive="true",
                Fields=_FIELDS, SortBy="SortName",
                StartIndex=start, Limit=_PAGE)
            items = data.get("Items", [])
            for dto in items:
                yield self._item(dto)
            start += len(items)
            if start >= data.get("TotalRecordCount", 0) or not items:
                return

    def resume_rail(self) -> list[ResumeEntry]:
        out: list[ResumeEntry] = []
        resume = self._get(f"/Users/{self.user_id}/Items/Resume",
                           Fields=_FIELDS, MediaTypes="Video", Limit=12)
        for dto in resume.get("Items", []):
            pos = (dto.get("UserData") or {}).get("PlaybackPositionTicks")
            out.append(ResumeEntry(
                kind=ResumeKind.CONTINUE, item=self._item(dto),
                position_s=int(pos / _TICKS_PER_S) if pos else None,
                engaged_at=(dto.get("UserData") or {}).get("LastPlayedDate")))
        nextup = self._get("/Shows/NextUp", UserId=self.user_id,
                           Fields=_FIELDS, Limit=12)
        for dto in nextup.get("Items", []):
            out.append(ResumeEntry(kind=ResumeKind.NEXT, item=self._item(dto)))
        latest = self._http.get(f"/Users/{self.user_id}/Items/Latest",
                                params={"Fields": _FIELDS, "Limit": 12})
        latest.raise_for_status()
        for dto in latest.json():
            out.append(ResumeEntry(kind=ResumeKind.NEW, item=self._item(dto)))
        return out

    def report_progress(self, item: VideoItem, position_s: int) -> None:
        self._http.post("/Sessions/Playing/Progress", json={
            "ItemId": item.source.item_id,
            "PositionTicks": position_s * _TICKS_PER_S,
        }).raise_for_status()

    def close(self) -> None:
        self._http.close()
