"""Install, cache, and update Grayjay plugins.

Plugins are **never bundled** — the user picks a config URL, we fetch it
and its script at runtime, and cache both under
``$XDG_DATA_HOME/suite/grayjay/<plugin-id>/``. Each plugin carries its
own license (the FUTO first-party ones are AGPL-3.0); the manager keeps
the metadata a UI needs to show that before enabling anything.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urljoin

from .host import PluginConfig
from .provider import GrayjayProvider

#: FUTO's first-party index. Community plugins are just other URLs.
OFFICIAL_SOURCES = {
    "YouTube": "https://plugins.grayjay.app/Youtube/YoutubeConfig.json",
    "PeerTube": "https://plugins.grayjay.app/PeerTube/PeerTubeConfig.json",
    "Odysee": "https://plugins.grayjay.app/Odysee/OdyseeConfig.json",
    "Rumble": "https://plugins.grayjay.app/Rumble/RumbleConfig.json",
    "Twitch": "https://plugins.grayjay.app/Twitch/TwitchConfig.json",
    "Nebula": "https://plugins.grayjay.app/Nebula/NebulaConfig.json",
    "Bitchute": "https://plugins.grayjay.app/Bitchute/BitchuteConfig.json",
    "SoundCloud": "https://plugins.grayjay.app/SoundCloud/SoundCloudConfig.json",
}


def plugins_dir() -> str:
    data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(data, "suite", "grayjay")


@dataclass(frozen=True)
class InstalledPlugin:
    config: PluginConfig
    script_path: str
    config_path: str
    source_url: str

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    def load(self, settings: dict | None = None) -> GrayjayProvider:
        with open(self.script_path, encoding="utf-8") as f:
            return GrayjayProvider(self.config, f.read(), settings=settings)


class PluginManager:
    """Filesystem-backed plugin store."""

    def __init__(self, root: str | None = None, http_client=None):
        self.root = root or plugins_dir()
        self._client = http_client

    def _http(self):
        if self._client is None:
            import httpx
            self._client = httpx.Client(timeout=30.0, follow_redirects=True)
        return self._client

    # -- store ------------------------------------------------------------

    def installed(self) -> list[InstalledPlugin]:
        out: list[InstalledPlugin] = []
        if not os.path.isdir(self.root):
            return out
        for pid in sorted(os.listdir(self.root)):
            d = os.path.join(self.root, pid)
            cfg_p = os.path.join(d, "config.json")
            script_p = os.path.join(d, "script.js")
            if not (os.path.isfile(cfg_p) and os.path.isfile(script_p)):
                continue
            try:
                with open(cfg_p, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                continue
            out.append(InstalledPlugin(
                config=PluginConfig.from_dict(raw),
                script_path=script_p, config_path=cfg_p,
                source_url=raw.get("__sourceUrl") or raw.get("sourceUrl", "")))
        return out

    def get(self, plugin_id: str) -> InstalledPlugin | None:
        return next((p for p in self.installed() if p.id == plugin_id), None)

    def install(self, config_url: str) -> InstalledPlugin:
        """Fetch a plugin config + script and cache them."""
        client = self._http()
        raw = client.get(config_url).raise_for_status().json()
        config = PluginConfig.from_dict(raw)
        script_url = urljoin(config_url, config.script_url or "")
        script = client.get(script_url).raise_for_status().text

        d = os.path.join(self.root, config.id)
        os.makedirs(d, exist_ok=True)
        raw["__sourceUrl"] = config_url
        cfg_p, script_p = os.path.join(d, "config.json"), os.path.join(d, "script.js")
        with open(cfg_p, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)
        with open(script_p, "w", encoding="utf-8") as f:
            f.write(script)
        return InstalledPlugin(config=PluginConfig.from_dict(raw),
                               script_path=script_p, config_path=cfg_p,
                               source_url=config_url)

    def uninstall(self, plugin_id: str) -> bool:
        p = self.get(plugin_id)
        if p is None:
            return False
        import shutil
        shutil.rmtree(os.path.dirname(p.script_path), ignore_errors=True)
        return True

    # -- updates ----------------------------------------------------------

    def check_update(self, plugin: InstalledPlugin) -> int | None:
        """Remote version if newer than what's installed, else None.

        Plugin versions are integers that FUTO bumps often (the YouTube
        plugin is in the 300s) — checking is cheap and matters, since a
        stale extraction plugin simply stops working.
        """
        url = plugin.source_url or plugin.config.source_url
        if not url:
            return None
        try:
            raw = self._http().get(url).raise_for_status().json()
        except Exception:
            return None
        remote = int(raw.get("version") or 0)
        return remote if remote > plugin.config.version else None

    def update(self, plugin: InstalledPlugin) -> InstalledPlugin | None:
        """Reinstall when the remote version is newer."""
        if self.check_update(plugin) is None:
            return None
        return self.install(plugin.source_url or plugin.config.source_url)

    def update_all(self) -> list[str]:
        updated = []
        for p in self.installed():
            if self.update(p) is not None:
                updated.append(p.name)
        return updated
