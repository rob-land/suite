"""GrayjayProvider — a Grayjay plugin as a suite MediaProvider.

One class turns every Grayjay plugin the user installs into a backend
for all the suite shells: couch's rails, zoetrope's glasses rails, and
anything else driving ``suite_providers.aio``.

Plugin calls are synchronous (a JS engine + blocking HTTP), so each one
runs off the event loop on a dedicated owner thread — one per plugin,
because JS engines are thread-affine (a V8 isolate touched from a second
thread segfaults). That also serializes calls into the engine for free.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..media import (
    Capability,
    ContentType,
    MediaItem,
    StreamInfo,
)
from ..models import StereoConfidence, StereoFormat, StereoHint
from ..naming import video_stereo_hint
from .host import PluginConfig, PluginError, PluginHost

#: Source kinds we can hand to mpv directly, best first.
_STREAM_PRIORITY = ("HLSSource", "DashSource", "VideoUrlSource",
                    "DashManifestRawSource", "VideoUrlRangeSource")


def _sources(descriptor: Any) -> list[dict]:
    """Flatten a video descriptor into a list of source dicts.

    Plugins spell these several ways (``videoSources``, ``sources``, a
    bare array, or an object with numeric keys after marshalling).
    """
    if descriptor is None:
        return []
    if isinstance(descriptor, list):
        return [s for s in descriptor if isinstance(s, dict)]
    if not isinstance(descriptor, dict):
        return []
    for key in ("videoSources", "sources"):
        if isinstance(descriptor.get(key), list):
            return [s for s in descriptor[key] if isinstance(s, dict)]
    numeric = [descriptor[k] for k in sorted(descriptor, key=str)
               if k.isdigit() and isinstance(descriptor[k], dict)]
    return numeric


def pick_stream(descriptor: Any) -> dict | None:
    """Best playable source for mpv: prefer adaptive manifests, then the
    highest-resolution progressive URL."""
    srcs = [s for s in _sources(descriptor) if s.get("url")]
    if not srcs:
        return None

    def rank(s: dict) -> tuple[int, int]:
        kind = s.get("plugin_type") or ""
        try:
            order = _STREAM_PRIORITY.index(kind)
        except ValueError:
            order = len(_STREAM_PRIORITY)
        return (order, -int(s.get("height") or s.get("width") or 0))

    return sorted(srcs, key=rank)[0]


def _thumbnail(item: dict) -> str | None:
    thumbs = ((item.get("thumbnails") or {}).get("sources")
              or item.get("thumbnails") or [])
    if isinstance(thumbs, list) and thumbs:
        best = max((t for t in thumbs if isinstance(t, dict)),
                   key=lambda t: t.get("quality") or 0, default=None)
        if best:
            return best.get("url")
    return None


def _make_host(config: PluginConfig, script: str, engine: str):
    """In-process engine, or the Node sidecar.

    ``engine="auto"`` prefers Node when it is installed: it is the only
    engine that runs every plugin (YouTube's bundled JSDOM and its
    runtime-built signature decryptor defeat the embeddable ones). It
    falls back to an in-process engine otherwise, which is plenty for
    API-shaped plugins like PeerTube and Odysee.
    """
    from .sidecar import SidecarPlugin, node_available

    if engine == "node":
        return SidecarPlugin(config, script)
    if engine == "auto" and node_available():
        try:
            return SidecarPlugin(config, script)
        except PluginError:
            pass          # fall through to an in-process engine
    return PluginHost(config, script,
                      engine="auto" if engine == "auto" else engine)


class GrayjayProvider:
    """Adapts one loaded plugin to the suite's provider surface.

    Deliberately duck-typed rather than subclassing ``MediaProvider``:
    Grayjay plugins have no accounts of their own (the shells' profile
    credentials don't apply), so the ``credentials`` arguments are
    accepted and ignored.
    """

    def __init__(self, config: PluginConfig, script: str, *,
                 settings: dict | None = None, call_timeout: float = 45.0,
                 engine: str = "auto"):
        self.config = config
        self.provider_id = f"grayjay:{config.id}"
        self.display_name = config.name
        self.source_id = self.provider_id
        self.source_display_name = config.name
        self._call_timeout = call_timeout
        # JS engines are thread-affine — a V8 isolate touched from a
        # second thread segfaults — so one dedicated worker owns the
        # engine for this plugin's whole lifetime: it is created there,
        # every call runs there, and it is closed there.
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"grayjay-{config.id[:8]}")
        self._host = self._pool.submit(
            lambda: _make_host(config, script, engine)).result()
        self._pool.submit(lambda: self._host.enable(settings)).result()

    # -- plumbing ---------------------------------------------------------

    async def _call(self, method: str, *args: Any) -> Any:
        """Run a plugin method on its owner thread, off the event loop."""
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(
            self._pool, lambda: self._host.call(method, *args))
        return await asyncio.wait_for(fut, timeout=self._call_timeout)

    def _to_item(self, v: dict) -> MediaItem:
        author = v.get("author") or {}
        vid = v.get("id") or {}
        stereo = video_stereo_hint(v.get("name") or "")
        if not stereo.format.is_stereo:
            stereo = StereoHint(StereoFormat.MONO, StereoConfidence.NONE)
        return MediaItem(
            provider_id=self.source_id,
            provider_item_id=str(vid.get("value") or v.get("url") or ""),
            title=v.get("name") or "",
            content_type=ContentType.MOVIE,
            description=v.get("description") or "",
            runtime_seconds=int(v.get("duration") or 0) or None,
            poster_url=_thumbnail(v),
            stereo=stereo,
            extras={
                "grayjay_url": v.get("url"),
                "author": author.get("name"),
                "is_live": bool(v.get("isLive")),
                "plugin": self.config.name,
            },
        )

    @staticmethod
    def _results(pager: Any) -> list[dict]:
        if isinstance(pager, dict):
            res = pager.get("results")
            if isinstance(res, list):
                return [v for v in res if isinstance(v, dict)]
        if isinstance(pager, list):
            return [v for v in pager if isinstance(v, dict)]
        return []

    # -- provider surface -------------------------------------------------

    def get_capabilities(self) -> set[Capability]:
        caps = {Capability.MOVIES}
        if self._host.has("search"):
            caps.add(Capability.SEARCH)
        return caps

    async def authenticate(self, credentials=None):
        from ..media import AuthStatus
        return AuthStatus(ok=True)

    async def list_library(self, content_type=None, credentials=None,
                           max_content_rating_index=None,
                           limit: int = 60) -> list[MediaItem]:
        """The plugin's home feed."""
        if not self._host.has("getHome"):
            return []
        pager = await self._call("getHome")
        return [self._to_item(v) for v in self._results(pager)[:limit]]

    async def search(self, query: str, credentials=None,
                     max_content_rating_index=None) -> list[MediaItem]:
        if not self._host.has("search"):
            return []
        pager = await self._call("search", query, None, None, None)
        return [self._to_item(v) for v in self._results(pager)]

    async def get_continue_watching(self, credentials=None,
                                    max_content_rating_index=None,
                                    limit: int = 12) -> list[MediaItem]:
        return []  # plugins hold no watch state; the shells' DB does

    async def get_stream_url(self, item: MediaItem,
                             credentials=None) -> StreamInfo:
        url = (item.extras or {}).get("grayjay_url")
        if not url:
            raise RuntimeError(f"{item.title}: no plugin URL to resolve")
        details = await self._call("getContentDetails", url)
        source = pick_stream((details or {}).get("video"))
        if not source or not source.get("url"):
            raise RuntimeError(
                f"{self.config.name} returned no playable source for "
                f"{item.title}")
        opts, headers = {}, {}
        for key, value in (source.get("requestModifier") or {}).items():
            if key == "headers" and isinstance(value, dict):
                headers.update(value)
        return StreamInfo(url=await self._playable_url(source, item),
                          mpv_options=opts, headers=headers,
                          stereo=item.stereo)

    async def _playable_url(self, source: dict, item: MediaItem) -> str:
        """The URL to hand a player, proxying the source if it needs it.

        A ``DashManifestRawSource`` names itself accurately: the plugin
        builds the manifest, and the source's own ``url`` is a media
        endpoint no player can open on its own — YouTube's is a SABR
        endpoint that speaks a protocol mpv has never heard of. For those
        we publish a local DASH URL and let the plugin do the streaming,
        inside the session the server actually accepts.
        """
        live_id = source.get("__liveId")
        serve = getattr(self._host, "serve", None)
        if source.get("plugin_type") != "DashManifestRawSource" or not live_id:
            return source["url"]
        if serve is None:
            raise RuntimeError(
                f"{item.title} needs the plugin to stream it, which requires "
                f"the Node sidecar (engine={self._host.engine_name})")
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(self._pool, lambda: serve(live_id))
        url = await asyncio.wait_for(fut, timeout=self._call_timeout)
        if not url:
            raise RuntimeError(f"{item.title}: plugin served no manifest")
        return url

    async def report_progress(self, item, position_seconds, credentials=None,
                              completed: bool = False) -> None:
        return None

    async def close(self) -> None:
        """Close the engine on its owner thread, then retire the pool."""
        try:
            self._pool.submit(self._host.close).result(timeout=10)
        finally:
            self._pool.shutdown(wait=False)

    @property
    def logs(self) -> list[str]:
        return self._host.logs
