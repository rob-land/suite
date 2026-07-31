"""Python driver for the Node plugin sidecar.

Presents the same surface as :class:`~suite_providers.grayjay.host.PluginHost`
(``has`` / ``call`` / ``enable`` / ``logs`` / ``close``) so
``GrayjayProvider`` can drive either an in-process engine or Node.

Node exists as an engine because the embeddable Python engines can't run
the heavier plugins: QuickJS rejects YouTube's bundled JSDOM and
miscompiles its runtime-built signature decryptor, and the STPyV8 wheel
fails ICU init. Under Node the same plugin runs unmodified — JSDOM,
botguard attestation, signature solving and all.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
from typing import Any

from ..host import PluginConfig, PluginError

HERE = pathlib.Path(__file__).parent
SIDECAR_JS = HERE / "sidecar.mjs"
PRELUDE = HERE.parent / "prelude.js"


def node_available(candidate: str | None = None) -> str | None:
    """Path to a usable `node`, or None. Node 18+ has fetch built in."""
    exe = candidate or os.environ.get("SUITE_NODE") or shutil.which("node")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        major = int(out.lstrip("v").split(".")[0])
        return exe if major >= 18 else None
    except Exception:
        return None


class SidecarPlugin:
    """One plugin running in a Node child process."""

    def __init__(self, config: PluginConfig, script: str, *,
                 timeout: float = 120.0, node: str | None = None):
        # An explicit path is validated the same way as a discovered one,
        # so a bad override fails with a clear message instead of a raw
        # FileNotFoundError from the spawn.
        exe = node_available(node)
        if not exe:
            raise PluginError(
                "the node engine needs Node 18+ on PATH (or $SUITE_NODE); "
                f"{node!r} is not usable" if node else
                "the node engine needs Node 18+ on PATH (or $SUITE_NODE)")
        self.config = config
        self.timeout = timeout
        self._seq = 0
        self._lock = threading.Lock()
        self._logs: list[str] = []

        # The sidecar reads config and script from disk; a temp dir keeps
        # this independent of where (or whether) the plugin is cached.
        self._dir = tempfile.mkdtemp(prefix="suite-grayjay-")
        cfg_path = pathlib.Path(self._dir) / "config.json"
        script_path = pathlib.Path(self._dir) / "script.js"
        cfg_path.write_text(json.dumps(config.raw), encoding="utf-8")
        script_path.write_text(script, encoding="utf-8")

        self._proc = subprocess.Popen(
            [exe, str(SIDECAR_JS), str(cfg_path), str(script_path), str(PRELUDE)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        ready = self._read(expect_id=0)
        if not ready.get("ok"):
            raise PluginError(f"{config.name}: sidecar failed to start")

    # -- rpc --------------------------------------------------------------

    def _read(self, expect_id: int) -> dict:
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise PluginError(
                    f"{self.config.name}: sidecar exited "
                    f"(code {self._proc.poll()})")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue      # stray output is never protocol
            if msg.get("id") != expect_id:
                continue
            for entry in msg.get("logs") or []:
                self._logs.append(str(entry)[:2000])
            del self._logs[:-200]
            return msg

    def _rpc(self, **payload: Any) -> Any:
        with self._lock:
            self._seq += 1
            payload["id"] = self._seq
            try:
                self._proc.stdin.write(json.dumps(payload) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError) as e:
                raise PluginError(f"{self.config.name}: sidecar gone") from e
            msg = self._read(expect_id=self._seq)
        if not msg.get("ok"):
            raise PluginError(f"{self.config.name}: {msg.get('error')}")
        return msg.get("result")

    # -- PluginHost-compatible surface -------------------------------------

    def has(self, method: str) -> bool:
        try:
            return bool(self._rpc(method="has", name=method))
        except PluginError:
            return False

    def call(self, method: str, *args: Any) -> Any:
        return self._rpc(method="call", name=method, args=list(args))

    def default_settings(self) -> dict:
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

    def enable(self, settings: dict | None = None) -> None:
        merged = self.default_settings()
        merged.update(settings or {})
        self._rpc(method="context", config=self.config.raw, settings=merged)
        if self.has("enable"):
            self.call("enable", self.config.raw, merged, "")

    @property
    def engine_name(self) -> str:
        return "node"

    @property
    def logs(self) -> list[str]:
        return list(self._logs)

    def close(self) -> None:
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
        finally:
            shutil.rmtree(self._dir, ignore_errors=True)
