"""Grayjay plugin support for the suite.

Grayjay (FUTO) plugins are JavaScript modules that extract content from
streaming platforms. They are **not bundled**: the user chooses which
plugin URLs to install, the manager fetches them at runtime, and each
carries its own license (FUTO's first-party plugins are AGPL-3.0,
compatible with this GPL-3.0 package).

    from suite_providers.grayjay import PluginManager

    mgr = PluginManager()
    plugin = mgr.install(OFFICIAL_SOURCES["PeerTube"])
    provider = plugin.load()          # a suite provider
    items = await provider.search("blender")
    stream = await provider.get_stream_url(items[0])
"""
from .host import PluginConfig, PluginError, PluginHost, host_allowed
from .manager import (
    OFFICIAL_SOURCES,
    InstalledPlugin,
    PluginManager,
    plugins_dir,
)
from .provider import GrayjayProvider, pick_stream

__all__ = [
    "GrayjayProvider",
    "InstalledPlugin",
    "OFFICIAL_SOURCES",
    "PluginConfig",
    "PluginError",
    "PluginHost",
    "PluginManager",
    "host_allowed",
    "pick_stream",
    "plugins_dir",
]
