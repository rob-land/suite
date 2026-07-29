"""Filename → stereo-format inference.

The shared rules for `StereoConfidence.NAME` hints: Kodi's 3D filename
flags (the de-facto standard the ecosystem — including Jellyfin's
parser — grew from), plus ripsaw's output naming (`*.fsbs.mkv`,
`*.hsbs.mkv`). Pure functions; every provider and shell uses these
instead of growing its own regexes.
"""
from __future__ import annotations

import re

from .models import StereoConfidence, StereoFormat, StereoHint

# Kodi-style flags appear as separated tokens: "Movie.3D.HSBS.mkv",
# "Movie (2010) 3D-FTAB.mkv", "movie.3d.h-sbs.mkv" …
_SEP = r"[ ._\-\[\]()]"

_VIDEO_RULES: tuple[tuple[str, StereoFormat], ...] = (
    (rf"{_SEP}(h[\-.]?sbs|half[\-.]?sbs){_SEP}?", StereoFormat.SBS_HALF),
    (rf"{_SEP}(f[\-.]?sbs|full[\-.]?sbs){_SEP}?", StereoFormat.SBS_FULL),
    (rf"\.fsbs\.", StereoFormat.SBS_FULL),          # ripsaw output
    (rf"\.hsbs\.", StereoFormat.SBS_HALF),          # ripsaw output
    (rf"{_SEP}(h[\-.]?tab|half[\-.]?tab|h[\-.]?ou|half[\-.]?ou){_SEP}?",
     StereoFormat.TAB_HALF),
    (rf"{_SEP}(f[\-.]?tab|full[\-.]?tab|f[\-.]?ou|full[\-.]?ou){_SEP}?",
     StereoFormat.TAB_FULL),
    (rf"{_SEP}sbs{_SEP}?", StereoFormat.SBS_HALF),  # bare SBS: half is the
                                                    # common 3D-rip meaning
    (rf"{_SEP}(tab|ou)e?{_SEP}?", StereoFormat.TAB_HALF),
    (rf"{_SEP}mvc{_SEP}?", StereoFormat.MVC),
)

# "3D" alone marks stereo without packing; report UNKNOWN-stereo so the
# player probes rather than guessing a packing.
_BARE_3D = re.compile(rf"{_SEP}3d{_SEP}?", re.IGNORECASE)

_PHOTO_STEREO_EXTS = {".mpo": StereoFormat.MPO, ".jps": StereoFormat.SBS_FULL}


def video_stereo_hint(name: str) -> StereoHint:
    """Infer a stereo hint from a video filename (basename or path)."""
    low = name.lower()
    for pattern, fmt in _VIDEO_RULES:
        if re.search(pattern, low):
            return StereoHint(fmt, StereoConfidence.NAME)
    if _BARE_3D.search(low):
        return StereoHint(StereoFormat.UNKNOWN, StereoConfidence.NAME)
    return StereoHint.mono()


def photo_stereo_hint(name: str) -> StereoHint:
    """Infer a stereo hint from a photo filename."""
    low = name.lower()
    for ext, fmt in _PHOTO_STEREO_EXTS.items():
        if low.endswith(ext):
            return StereoHint(fmt, StereoConfidence.NAME)
    if _BARE_3D.search(low) or "stereo" in low or "sbs" in low:
        return StereoHint(StereoFormat.UNKNOWN, StereoConfidence.NAME)
    return StereoHint.mono()


def jellyfin_format_to_stereo(value: str | None) -> StereoHint:
    """Map Jellyfin's `Video3DFormat` DTO values to the suite vocabulary
    (SERVER confidence)."""
    mapping = {
        "HalfSideBySide": StereoFormat.SBS_HALF,
        "FullSideBySide": StereoFormat.SBS_FULL,
        "HalfTopAndBottom": StereoFormat.TAB_HALF,
        "FullTopAndBottom": StereoFormat.TAB_FULL,
        "MVC": StereoFormat.MVC,
    }
    if value in mapping:
        return StereoHint(mapping[value], StereoConfidence.SERVER)
    return StereoHint.mono()
