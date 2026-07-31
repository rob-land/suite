"""Grayjay host tests — offline (a synthetic plugin), no network."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest.importorskip("quickjs")

from suite_providers.grayjay import (  # noqa: E402
    PluginConfig,
    PluginHost,
    host_allowed,
    pick_stream,
)

CONFIG = {
    "id": "test-plugin", "name": "TestPlugin", "scriptUrl": "./s.js",
    "version": 3, "allowUrls": ["example.com"],
    "constants": {"baseUrl": "https://example.com"},
    "settings": [
        {"variable": "hdr", "type": "Header"},
        {"variable": "useFoo", "type": "Boolean", "default": "true"},
        {"variable": "mode", "type": "Dropdown", "default": "2"},
        {"variable": "label", "type": "Text", "default": "hi"},
    ],
}

SCRIPT = """
source.enable = function(conf, settings, state) { this._s = settings; };
source.getHome = function() {
    return new VideoPager([new PlatformVideo({
        id: new PlatformID("Test", "v1", "p"),
        name: "Item One", url: plugin.config.constants.baseUrl + "/v1",
        duration: 120,
        thumbnails: new Thumbnails([new Thumbnail("https://example.com/t.jpg", 720)]),
        author: new PlatformAuthorLink(null, "Author", "https://example.com/a"),
    })], true, {});
};
source.settingsSeen = function() { return this._s; };
source.getContentDetails = function(url) {
    return new PlatformVideoDetails({
        name: "Item One",
        video: new MuxVideoSourceDescriptor([
            new VideoUrlSource({name: "480p", url: "https://example.com/480.mp4", height: 480}),
            new HLSSource({name: "HLS", url: "https://example.com/m.m3u8"}),
        ]),
    });
};
source.urlParts = function(u) {
    const x = new URL(u);
    return [x.protocol, x.host, x.pathname, x.searchParams.get("q")];
};
source.blocked = function() { return http.GET("https://evil.test/x", {}).code; };
source.timerWorks = function() { let hit = 0; setTimeout(() => { hit = 1; }, 1); return hit; };
"""


def _host() -> PluginHost:
    h = PluginHost(PluginConfig.from_dict(CONFIG), SCRIPT)
    h.enable()
    return h


# --- allowUrls --------------------------------------------------------------

def test_allow_urls_matches_domain_and_subdomains():
    assert host_allowed("example.com", ("example.com",))
    assert host_allowed("cdn.example.com", ("example.com",))
    assert not host_allowed("notexample.com", ("example.com",))
    assert not host_allowed("evil.test", ("example.com",))
    assert host_allowed("anything.at.all", ("everywhere",))
    assert not host_allowed("example.com", ())


def test_blocked_host_returns_403_without_leaving_the_sandbox():
    h = _host()
    assert h.call("blocked") == 403
    h.close()


# --- runtime surface --------------------------------------------------------

def test_pagers_and_platform_types_marshal():
    h = _host()
    home = h.call("getHome")
    assert home["hasMore"] is True
    item = home["results"][0]
    assert item["name"] == "Item One"
    assert item["duration"] == 120
    assert item["id"]["value"] == "v1"
    assert item["author"]["name"] == "Author"
    assert item["thumbnails"]["sources"][0]["quality"] == 720
    # plugin.config.constants is populated before any call
    assert item["url"] == "https://example.com/v1"
    h.close()


def test_settings_defaults_are_typed():
    h = _host()
    seen = h.call("settingsSeen")
    assert seen["useFoo"] is True      # Boolean, not the string "true"
    assert seen["mode"] == 2           # Dropdown index as int
    assert seen["label"] == "hi"
    assert "hdr" not in seen           # Headers aren't settings
    h.close()


def test_url_class_is_available_to_plugins():
    h = _host()
    proto, host, path, q = h.call(
        "urlParts", "https://example.com:8443/a/b?q=hello#frag")
    assert (proto, host, path, q) == ("https:", "example.com:8443", "/a/b", "hello")
    h.close()


def test_timers_run_inline():
    h = _host()
    assert h.call("timerWorks") == 1
    h.close()


def test_missing_method_is_reported():
    h = _host()
    assert h.has("getHome") and not h.has("nopeNotHere")
    h.close()


# --- stream selection -------------------------------------------------------

def test_pick_stream_prefers_adaptive_then_resolution():
    descriptor = {"videoSources": [
        {"plugin_type": "VideoUrlSource", "url": "u1", "height": 480},
        {"plugin_type": "HLSSource", "url": "hls"},
    ]}
    assert pick_stream(descriptor)["url"] == "hls"
    progressive = {"videoSources": [
        {"plugin_type": "VideoUrlSource", "url": "low", "height": 480},
        {"plugin_type": "VideoUrlSource", "url": "high", "height": 1080},
    ]}
    assert pick_stream(progressive)["url"] == "high"


def test_pick_stream_handles_marshalled_shapes():
    # bare array, and the numeric-key object marshalling can produce
    assert pick_stream([{"plugin_type": "HLSSource", "url": "a"}])["url"] == "a"
    assert pick_stream({"0": {"plugin_type": "HLSSource", "url": "b"}})["url"] == "b"
    assert pick_stream(None) is None
    assert pick_stream({"videoSources": []}) is None


def test_descriptor_from_plugin_yields_a_playable_source():
    h = _host()
    details = h.call("getContentDetails", "https://example.com/v1")
    best = pick_stream(details["video"])
    assert best["url"] == "https://example.com/m.m3u8"   # HLS wins
    h.close()


# --- config -----------------------------------------------------------------

def test_plugin_config_parses_metadata():
    cfg = PluginConfig.from_dict(json.loads(json.dumps(CONFIG)))
    assert cfg.id == "test-plugin"
    assert cfg.version == 3
    assert cfg.allow_urls == ("example.com",)
    assert cfg.allow_eval is False


# --- node sidecar -----------------------------------------------------------

def test_sidecar_runs_a_plugin_when_node_is_present():
    """The sidecar exposes the same surface as the in-process host."""
    from suite_providers.grayjay.sidecar import SidecarPlugin, node_available

    if not node_available():
        pytest.skip("node 18+ not installed")
    p = SidecarPlugin(PluginConfig.from_dict(CONFIG), SCRIPT)
    try:
        p.enable()
        assert p.engine_name == "node"
        assert p.has("getHome") and not p.has("nopeNotHere")
        home = p.call("getHome")
        assert home["results"][0]["name"] == "Item One"
        # plugin.config.constants reaches the plugin in the sidecar too
        assert home["results"][0]["url"] == "https://example.com/v1"
        # typed settings defaults survive the RPC hop
        seen = p.call("settingsSeen")
        assert seen["useFoo"] is True and seen["mode"] == 2
        # allowUrls is enforced inside the sidecar's HTTP worker
        assert p.call("blocked") == 403
    finally:
        p.close()


def test_sidecar_reports_missing_node_clearly():
    from suite_providers.grayjay.host import PluginError
    from suite_providers.grayjay.sidecar import SidecarPlugin

    with pytest.raises(PluginError, match="Node 18"):
        SidecarPlugin(PluginConfig.from_dict(CONFIG), SCRIPT,
                      node="/nonexistent/node")
