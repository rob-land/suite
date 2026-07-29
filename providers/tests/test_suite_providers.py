"""Tests for models, naming inference, and the local providers."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from suite_providers import (  # noqa: E402
    StereoConfidence,
    StereoFormat,
)
from suite_providers.localfiles import (  # noqa: E402
    LocalPhotoLibrary,
    LocalVideoLibrary,
)
from suite_providers.naming import (  # noqa: E402
    jellyfin_format_to_stereo,
    photo_stereo_hint,
    video_stereo_hint,
)


# --- naming: video ----------------------------------------------------------

def test_ripsaw_output_names():
    assert video_stereo_hint("Avatar (2009).fsbs.mkv").format is StereoFormat.SBS_FULL
    assert video_stereo_hint("Avatar (2009).hsbs.mkv").format is StereoFormat.SBS_HALF


def test_kodi_flags():
    assert video_stereo_hint("Movie.3D.HSBS.mkv").format is StereoFormat.SBS_HALF
    assert video_stereo_hint("Movie 3D-FSBS.mkv").format is StereoFormat.SBS_FULL
    assert video_stereo_hint("Movie.3D.H-TAB.mkv").format is StereoFormat.TAB_HALF
    assert video_stereo_hint("Movie.3D.MVC.mkv").format is StereoFormat.MVC


def test_bare_3d_is_unknown_stereo():
    h = video_stereo_hint("Movie.3D.mkv")
    assert h.format is StereoFormat.UNKNOWN
    assert h.confidence is StereoConfidence.NAME


def test_plain_names_are_mono():
    h = video_stereo_hint("Regular Movie (2020).mkv")
    assert h.format is StereoFormat.MONO
    # "3della" or words containing sbs shouldn't trip separated-token rules
    assert video_stereo_hint("absbsolute.mkv").format is StereoFormat.MONO


# --- naming: photo + jellyfin mapping ---------------------------------------

def test_photo_hints():
    assert photo_stereo_hint("holiday.mpo").format is StereoFormat.MPO
    assert photo_stereo_hint("shot.jps").format is StereoFormat.SBS_FULL
    assert photo_stereo_hint("flat.jpg").format is StereoFormat.MONO


def test_jellyfin_mapping():
    h = jellyfin_format_to_stereo("HalfSideBySide")
    assert h.format is StereoFormat.SBS_HALF
    assert h.confidence is StereoConfidence.SERVER
    assert jellyfin_format_to_stereo(None).format is StereoFormat.MONO


# --- local providers --------------------------------------------------------

def test_local_video_walk(tmp_path):
    d = tmp_path / "Avatar (2009)"
    d.mkdir()
    (d / "Avatar (2009).fsbs.mkv").touch()
    (d / "poster.jpg").touch()
    (tmp_path / "Extras").mkdir()
    (tmp_path / "Extras" / "bonus.mkv").touch()
    lib = LocalVideoLibrary([str(tmp_path)])
    items = list(lib.videos())
    assert len(items) == 1
    v = items[0]
    assert v.title == "Avatar"
    assert v.year == 2009
    assert v.stereo.format is StereoFormat.SBS_FULL
    assert v.poster_url and v.poster_url.endswith("poster.jpg")


def test_local_photo_pairs_and_mpo(tmp_path):
    (tmp_path / "trip_l.jpg").touch()
    (tmp_path / "trip_r.jpg").touch()
    (tmp_path / "beach.mpo").write_bytes(b"\xff\xd8fake")
    lib = LocalPhotoLibrary([str(tmp_path)])
    items = {p.title: p for p in lib.photos()}
    assert items["beach"].stereo.format is StereoFormat.MPO
    pair = items["trip_l"]
    assert pair.stereo.format is StereoFormat.STEREO_PAIR
    assert pair.right_source and pair.right_source.path.endswith("trip_r.jpg")
    assert lib.original_bytes(items["beach"]).startswith(b"\xff\xd8")
