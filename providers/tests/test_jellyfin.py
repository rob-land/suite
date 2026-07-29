"""JellyfinVideoLibrary against a mocked transport."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

httpx = pytest.importorskip("httpx")

from suite_providers import ResumeKind, StereoConfidence, StereoFormat  # noqa: E402
from suite_providers.jellyfin import JellyfinVideoLibrary  # noqa: E402


def _lib(handler):
    lib = JellyfinVideoLibrary("http://jf.local", "tok", "u1")
    lib._http = httpx.Client(
        base_url="http://jf.local", transport=httpx.MockTransport(handler))
    return lib


ITEMS = {
    "Items": [
        {"Id": "a", "Name": "Avatar", "ProductionYear": 2009,
         "RunTimeTicks": 97_200_000_000, "Video3DFormat": "HalfSideBySide",
         "Path": "/lib/Avatar (2009) 3D.HSBS.mkv"},
        {"Id": "b", "Name": "Tron", "ProductionYear": 2010,
         "Path": "/lib/Tron (2010).3d.fsbs.mkv"},
        {"Id": "c", "Name": "Flat", "Path": "/lib/Flat (2011).mkv"},
    ],
    "TotalRecordCount": 3,
}


def test_videos_maps_server_tag_and_name_fallback():
    def handler(request):
        assert request.url.path == "/Users/u1/Items"
        return httpx.Response(200, json=ITEMS)

    vids = {v.title: v for v in _lib(handler).videos()}
    a = vids["Avatar"]
    assert a.stereo.format is StereoFormat.SBS_HALF
    assert a.stereo.confidence is StereoConfidence.SERVER
    assert a.duration_s == 9720
    # No server tag on Tron -> filename inference kicks in.
    b = vids["Tron"]
    assert b.stereo.format is StereoFormat.SBS_FULL
    assert b.stereo.confidence is StereoConfidence.NAME
    assert vids["Flat"].stereo.format is StereoFormat.MONO


def test_resume_rail_kinds():
    def handler(request):
        p = request.url.path
        if p == "/Users/u1/Items/Resume":
            return httpx.Response(200, json={"Items": [
                {"Id": "a", "Name": "Avatar",
                 "UserData": {"PlaybackPositionTicks": 600_0000000,
                              "LastPlayedDate": "2026-07-27T00:00:00Z"}}]})
        if p == "/Shows/NextUp":
            return httpx.Response(200, json={"Items": [
                {"Id": "e2", "Name": "Ep 2"}]})
        if p == "/Users/u1/Items/Latest":
            return httpx.Response(200, json=[{"Id": "n", "Name": "Fresh"}])
        raise AssertionError(p)

    rail = _lib(handler).resume_rail()
    kinds = [e.kind for e in rail]
    assert kinds == [ResumeKind.CONTINUE, ResumeKind.NEXT, ResumeKind.NEW]
    assert rail[0].position_s == 600
