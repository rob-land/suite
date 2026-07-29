"""Async JellyfinProvider (moved from couch) against a mocked transport."""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

httpx = pytest.importorskip("httpx")

from suite_providers import (  # noqa: E402
    SourceConfig,
    StereoConfidence,
    StereoFormat,
)
from suite_providers.aio import JellyfinProvider  # noqa: E402

CREDS = {"access_token": "tok", "user_id": "u1"}

ITEMS = {
    "Items": [
        {"Id": "a", "Name": "Avatar", "Type": "Movie",
         "ProductionYear": 2009, "Video3DFormat": "HalfSideBySide",
         "Path": "/lib/Avatar (2009) 3D.HSBS.mkv"},
        {"Id": "b", "Name": "Tron", "Type": "Movie",
         "ProductionYear": 2010, "Path": "/lib/Tron (2010).3d.fsbs.mkv"},
        {"Id": "c", "Name": "Flat", "Type": "Movie",
         "Path": "/lib/Flat (2011).mkv"},
    ],
    "TotalRecordCount": 3,
}


def _provider(handler) -> JellyfinProvider:
    p = JellyfinProvider()
    p.configure(SourceConfig(id="jf1", provider="jellyfin",
                             display_name="Test JF",
                             config={"server_url": "http://jf.local"}))
    p._client = httpx.AsyncClient(base_url="http://jf.local",
                                  transport=httpx.MockTransport(handler))
    return p


def test_library_maps_stereo_server_tag_and_name_fallback():
    def handler(request):
        assert request.url.path.endswith("/Items")
        return httpx.Response(200, json=ITEMS)

    async def run():
        p = _provider(handler)
        from suite_providers import ContentType
        items = await p.list_library(ContentType.MOVIE, CREDS)
        await p.close()
        return {i.title: i for i in items}

    vids = asyncio.run(run())
    a = vids["Avatar"]
    assert a.stereo.format is StereoFormat.SBS_HALF
    assert a.stereo.confidence is StereoConfidence.SERVER
    b = vids["Tron"]
    assert b.stereo.format is StereoFormat.SBS_FULL
    assert b.stereo.confidence is StereoConfidence.NAME
    assert vids["Flat"].stereo.format is StereoFormat.MONO


def test_stream_info_carries_the_stereo_hint():
    def handler(request):
        if request.url.path.endswith("/Items"):
            return httpx.Response(200, json=ITEMS)
        if "PlaybackInfo" in request.url.path:
            return httpx.Response(200, json={
                "MediaSources": [{"Id": "ms1", "SupportsDirectPlay": True,
                                  "Container": "mkv"}]})
        return httpx.Response(200, json={})

    async def run():
        from suite_providers import ContentType
        p = _provider(handler)
        items = await p.list_library(ContentType.MOVIE, CREDS)
        avatar = next(i for i in items if i.title == "Avatar")
        stream = await p.get_stream_url(avatar, CREDS)
        await p.close()
        return stream

    stream = asyncio.run(run())
    # The 3D-configured player reads this; a 2D player just ignores it.
    assert stream.stereo.format is StereoFormat.SBS_HALF
    assert "a" in stream.url
