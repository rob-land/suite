"""Grayjay plugin host: a QuickJS sandbox with Grayjay's runtime bridges.

Grayjay plugins (AGPL-3.0, fetched at runtime from the user's chosen
sources — never bundled) are plain JavaScript written against a small
host surface: an ``http`` package, a ``bridge`` utility object, and the
Platform*/​*Pager classes. :mod:`prelude.js` implements that surface on
top of three synchronous Python callables installed here.

QuickJS (not V8) because the plugin API is *synchronous* — ``http.GET``
returns a response object, not a promise — and quickjs is the Python
engine that lets JS call back into Python inside one call stack.

Security posture mirrors Grayjay's: the plugin's declared ``allowUrls``
is enforced host-side (the script cannot reach anything else), ``eval``
stays off unless the config asks for it, and every call is wall-clock
bounded.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit

from .engines import make_engine

PRELUDE = (pathlib.Path(__file__).parent / "prelude.js").read_text()

DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


class PluginError(RuntimeError):
    """A plugin failed to load or a plugin call raised."""


@dataclass(frozen=True)
class PluginConfig:
    """A Grayjay plugin config (the JSON next to the script)."""
    id: str
    name: str
    script_url: str
    version: int = 0
    author: str = ""
    platform_url: str = ""
    source_url: str = ""
    repository_url: str = ""
    icon_url: str = ""
    allow_urls: tuple[str, ...] = ()
    allow_eval: bool = False
    packages: tuple[str, ...] = ()
    settings: tuple[dict, ...] = ()
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, d: dict) -> "PluginConfig":
        return cls(
            id=d.get("id") or d.get("name", "plugin"),
            name=d.get("name", "Plugin"),
            script_url=d.get("scriptUrl", ""),
            version=int(d.get("version") or 0),
            author=d.get("author", ""),
            platform_url=d.get("platformUrl", ""),
            source_url=d.get("sourceUrl", ""),
            repository_url=d.get("repositoryUrl", ""),
            icon_url=d.get("iconUrl", ""),
            allow_urls=tuple(d.get("allowUrls") or ()),
            allow_eval=bool(d.get("allowEval")),
            packages=tuple(d.get("packages") or ()),
            settings=tuple(d.get("settings") or ()),
            raw=d,
        )


def host_allowed(host: str, allow_urls: tuple[str, ...]) -> bool:
    """Grayjay's allowUrls semantics: bare domains match themselves and
    their subdomains; ``everywhere`` disables the restriction."""
    if not allow_urls:
        return False
    host = (host or "").lower()
    for rule in allow_urls:
        rule = rule.lower().strip()
        if rule in ("everywhere", "*"):
            return True
        # A leading dot means "domain and subdomains" (cookie-domain
        # spelling); YouTube's config uses it for the media CDN.
        # Without stripping it the suffix test can never match.
        rule = rule.split("://")[-1].split("/")[0].lstrip(".")
        if host == rule or host.endswith("." + rule):
            return True
    return False


class PluginHost:
    """One loaded plugin: its QuickJS context and the host bridges."""

    def __init__(self, config: PluginConfig, script: str, *,
                 http_client=None, timeout: float = 30.0,
                 memory_limit_mb: int = 256, engine: str = "auto"):
        self.config = config
        self.timeout = timeout
        self._log: list[str] = []
        self._own_client = http_client is None
        if http_client is None:
            import httpx
            http_client = httpx.Client(
                timeout=httpx.Timeout(timeout, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": DEFAULT_UA})
        self._http = http_client

        self.engine = make_engine(engine, memory_limit_mb=memory_limit_mb)
        self.ctx = self.engine
        for name, fn in (
            ("__host_http", self._bridge_http),
            ("__host_log", self._bridge_log),
            ("__host_sleep", self._bridge_sleep),
            ("__host_uuid", lambda: str(uuid.uuid4())),
            ("__host_parse_url", self._bridge_parse_url),
            ("__host_md5", self._bridge_md5),
            ("__host_b64encode", self._bridge_b64encode),
            ("__host_b64decode", self._bridge_b64decode),
        ):
            self.engine.bind(name, fn)

        self.engine.eval(PRELUDE)
        try:
            self.engine.eval(script)
        except Exception as e:
            raise PluginError(f"{config.name}: script failed to load: {e}") from e

    # -- bridges ---------------------------------------------------------

    def _bridge_log(self, message: str) -> None:
        self._log.append(str(message)[:2000])
        del self._log[:-200]

    def _bridge_sleep(self, ms: float) -> None:
        time.sleep(min(float(ms), 5000) / 1000.0)

    def _bridge_http(self, request_json: str) -> str:
        req = json.loads(request_json)
        url = req.get("url") or ""
        host = urlparse(url).hostname or ""
        if not host_allowed(host, self.config.allow_urls):
            return json.dumps({
                "code": 403, "headers": {}, "url": url,
                "body": f"blocked by allowUrls: {host}"})
        headers = {k: v for k, v in (req.get("headers") or {}).items()
                   if isinstance(v, str)}
        headers.setdefault("User-Agent", DEFAULT_UA)
        try:
            resp = self._http.request(
                req.get("method", "GET"), url,
                content=(req.get("body") or None), headers=headers)
            return json.dumps({
                "code": resp.status_code,
                "headers": {k.lower(): v for k, v in resp.headers.items()},
                "body": resp.text,
                "url": str(resp.url),
            })
        except Exception as e:
            return json.dumps({"code": 0, "headers": {}, "url": url,
                               "body": f"host request failed: {e}"})

    @staticmethod
    def _bridge_md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8", "surrogatepass")).hexdigest()

    @staticmethod
    def _bridge_b64encode(text: str) -> str:
        return base64.b64encode(text.encode("utf-8", "surrogatepass")).decode()

    @staticmethod
    def _bridge_b64decode(text: str) -> str:
        pad = "=" * (-len(text) % 4)
        return base64.b64decode(text + pad).decode("utf-8", "replace")

    @staticmethod
    def _bridge_parse_url(url: str, base: str = "") -> str:
        """WHATWG-ish URL parsing behind the prelude's URL class."""
        try:
            full = urljoin(base, url) if base else url
            p = urlsplit(full)
            if not p.scheme:
                return json.dumps({"ok": False})
            if not p.netloc:
                # Opaque-path URLs (about:blank, data:, blob:, javascript:)
                # are valid WHATWG URLs with an empty host — JSDOM uses
                # about:blank for its default document, so rejecting
                # these breaks any plugin that bundles a DOM.
                return json.dumps({
                    "ok": True, "href": full, "protocol": f"{p.scheme}:",
                    "hostname": "", "port": "", "host": "", "origin": "null",
                    "pathname": p.path or "",
                    "search": f"?{p.query}" if p.query else "",
                    "hash": f"#{p.fragment}" if p.fragment else "",
                    "username": "", "password": "",
                })
            port = f":{p.port}" if p.port else ""
            host = (p.hostname or "") + port
            return json.dumps({
                "ok": True, "href": full,
                "protocol": f"{p.scheme}:", "hostname": p.hostname or "",
                "port": str(p.port or ""), "host": host,
                "origin": f"{p.scheme}://{host}",
                "pathname": p.path or "/",
                "search": f"?{p.query}" if p.query else "",
                "hash": f"#{p.fragment}" if p.fragment else "",
                "username": p.username or "", "password": p.password or "",
            })
        except Exception:
            return json.dumps({"ok": False})

    # -- calling the plugin ----------------------------------------------

    def has(self, method: str) -> bool:
        try:
            return bool(self.engine.eval(f'__has_source_method("{method}")'))
        except Exception:
            return False

    def call(self, method: str, *args: Any) -> Any:
        """Invoke ``source.<method>(*args)``; returns marshalled JSON."""
        payload = json.dumps(list(args)).replace("\\", "\\\\").replace("'", "\\'")
        try:
            out = self.engine.eval(f"__call_source('{method}', '{payload}')")
        except Exception as e:
            raise PluginError(f"{self.config.name}.{method}: {e}") from e
        if out is None:
            return None
        try:
            return json.loads(out)
        except (TypeError, json.JSONDecodeError):
            return out

    def default_settings(self) -> dict:
        """Defaults from the config's settings schema, in the shape
        plugins expect (booleans as real booleans, dropdowns as index
        ints — Grayjay stores dropdown selections numerically)."""
        out: dict[str, Any] = {}
        for entry in self.config.settings:
            var, kind = entry.get("variable"), (entry.get("type") or "")
            if not var or kind == "Header":
                continue
            raw = entry.get("default")
            if kind == "Boolean":
                out[var] = str(raw).lower() == "true"
            elif kind == "Dropdown":
                try:
                    out[var] = int(raw)
                except (TypeError, ValueError):
                    out[var] = 0
            elif raw is not None:
                out[var] = raw
        return out

    def _set_context(self, settings: dict) -> None:
        """Populate the `plugin` global (config + settings) plugins read
        directly — Grayjay's host does this before any source.* call."""
        cfg = json.dumps(self.config.raw)
        st = json.dumps(settings)
        self.engine.bind("__ctx_config", lambda: cfg)
        self.engine.bind("__ctx_settings", lambda: st)
        self.engine.eval("__set_plugin_context(__ctx_config(), __ctx_settings())")

    def enable(self, settings: dict | None = None) -> None:
        """Grayjay calls source.enable(conf, settings, saveStateStr).

        ``conf`` carries the plugin's own config — including the
        ``constants`` block plugins read for things like a PeerTube
        instance baseUrl — and ``settings`` starts from the schema
        defaults so a plugin behaves as it would on a fresh install.
        """
        merged = self.default_settings()
        if not self.has("enable"):
            merged.update(settings or {})
            self._set_context(merged)
            return

        merged.update(settings or {})
        self._set_context(merged)
        self.call("enable", self.config.raw, merged, "")

    @property
    def logs(self) -> list[str]:
        return list(self._log)

    @property
    def engine_name(self) -> str:
        return self.engine.name

    def close(self) -> None:
        try:
            self.engine.close()
        except Exception:
            pass
        if self._own_client:
            try:
                self._http.close()
            except Exception:
                pass
