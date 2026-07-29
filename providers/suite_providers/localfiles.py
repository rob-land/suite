"""Local-files providers — the gold standard (full probe access).

Video: walks a ripsaw-style library (Jellyfin naming, `Title (Year)`
dirs, poster art). Photo: walks folders for stills including MPO/JPS and
explicit L/R pairs. Stereo hints start at NAME confidence; callers can
upgrade to PROBED via stereoscope's CLI (see ``probe_upgrade``).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator

from .models import (
    MediaSource,
    PhotoItem,
    ResumeEntry,
    StereoCapability,
    StereoConfidence,
    StereoFormat,
    StereoHint,
    VideoItem,
)
from .naming import photo_stereo_hint, video_stereo_hint
from .provider import PhotoLibrary, VideoLibrary

VIDEO_EXTS = (".mkv", ".mp4", ".m4v", ".mov", ".webm", ".m2ts", ".ts")
PHOTO_EXTS = (".mpo", ".jps", ".jpg", ".jpeg", ".png", ".heic", ".heif")
POSTERS = ("poster.jpg", "poster.png", "folder.jpg", "folder.png", "cover.jpg")
_YEAR_DIR = re.compile(r"^(?P<title>.+) \((?P<year>\d{4})\)$")


def _title_year(path: str) -> tuple[str, int | None]:
    parent = os.path.basename(os.path.dirname(path))
    m = _YEAR_DIR.match(parent)
    if m:
        return m.group("title"), int(m.group("year"))
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"(\.(fsbs|hsbs|sbs|tab|ou|3d))+$", "", stem,
                  flags=re.IGNORECASE), None


class LocalVideoLibrary(VideoLibrary):
    id = "local"
    stereo_capability = StereoCapability.NAME_INFERRED  # PROBED on demand

    def __init__(self, roots: list[str]):
        self.roots = [r for r in roots if os.path.isdir(r)]

    def ping(self) -> bool:
        return bool(self.roots)

    def videos(self) -> Iterator[VideoItem]:
        seen: set[str] = set()
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")
                               and d.lower() not in ("extras", "trailers")]
                poster = next((os.path.join(dirpath, p) for p in POSTERS
                               if os.path.isfile(os.path.join(dirpath, p))),
                              None)
                for fn in sorted(filenames):
                    if os.path.splitext(fn)[1].lower() not in VIDEO_EXTS:
                        continue
                    p = os.path.join(dirpath, fn)
                    real = os.path.realpath(p)
                    if real in seen:
                        continue
                    seen.add(real)
                    title, year = _title_year(p)
                    yield VideoItem(
                        source=MediaSource(self.id, real, path=p),
                        title=title,
                        year=year,
                        poster_url=poster,
                        stereo=video_stereo_hint(fn),
                    )

    def resume_rail(self) -> list[ResumeEntry]:
        return []  # local files carry no watch state (couch's DB will)


class LocalPhotoLibrary(PhotoLibrary):
    id = "local-photos"
    stereo_capability = StereoCapability.NAME_INFERRED

    def __init__(self, roots: list[str]):
        self.roots = [r for r in roots if os.path.isdir(r)]

    def ping(self) -> bool:
        return bool(self.roots)

    def photos(self) -> Iterator[PhotoItem]:
        seen: set[str] = set()
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                names = [f for f in filenames
                         if os.path.splitext(f)[1].lower() in PHOTO_EXTS
                         and not f.lower().startswith(
                             ("poster.", "folder.", "cover."))]
                for left, right in _pair(names):
                    p = os.path.join(dirpath, left)
                    real = os.path.realpath(p)
                    if real in seen:
                        continue
                    seen.add(real)
                    hint = (StereoHint(StereoFormat.STEREO_PAIR,
                                       StereoConfidence.NAME)
                            if right else photo_stereo_hint(left))
                    yield PhotoItem(
                        source=MediaSource(self.id, real, path=p),
                        title=os.path.splitext(left)[0],
                        stereo=hint,
                        right_source=(MediaSource(
                            self.id, os.path.join(dirpath, right),
                            path=os.path.join(dirpath, right))
                            if right else None),
                    )

    def original_bytes(self, item: PhotoItem) -> bytes | None:
        if item.source.path and os.path.isfile(item.source.path):
            with open(item.source.path, "rb") as f:
                return f.read()
        return None


_PAIRS = (("_l", "_r"), ("-l", "-r"), ("_left", "_right"), ("-left", "-right"))


def _pair(names: list[str]) -> list[tuple[str, str | None]]:
    by_lower = {n.lower(): n for n in names}
    used: set[str] = set()
    out: list[tuple[str, str | None]] = []
    for n in sorted(names):
        low = n.lower()
        if low in used:
            continue
        stem, ext = os.path.splitext(low)
        matched = False
        for ls, rs in _PAIRS:
            if stem.endswith(ls) and by_lower.get(stem[: -len(ls)] + rs + ext):
                out.append((n, by_lower[stem[: -len(ls)] + rs + ext]))
                used.update({low, stem[: -len(ls)] + rs + ext})
                matched = True
                break
            if stem.endswith(rs) and by_lower.get(stem[: -len(rs)] + ls + ext):
                used.add(low)
                matched = True
                break
        if not matched:
            out.append((n, None))
            used.add(low)
    return out


def probe_upgrade(item: VideoItem) -> VideoItem:
    """Upgrade a NAME/NONE hint to PROBED via stereoscope's CLI, when a
    local path exists and stereoscope is installed. Returns the item
    unchanged otherwise. Callers should cache results keyed on
    (path, mtime)."""
    if item.stereo.confidence is StereoConfidence.PROBED:
        return item
    exe = os.environ.get("STEREOSCOPE_BIN") or shutil.which("stereoscope")
    if not exe or not item.source.path:
        return item
    try:
        res = subprocess.run([exe, "probe", item.source.path],
                             capture_output=True, timeout=60, check=True)
        fmt = StereoFormat(json.loads(res.stdout).get("format", "unknown"))
    except Exception:
        return item
    from dataclasses import replace
    return replace(item, stereo=StereoHint(fmt, StereoConfidence.PROBED))
