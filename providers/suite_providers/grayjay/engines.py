"""JavaScript engine backends for the plugin host.

Two engines, one prelude. The bridge contract is identical: the engine
exposes a handful of ``__host_*`` functions to JS and evaluates source.

- **QuickJS** (``quickjs``): small, pure-Python-installable, plenty for
  plugins that only parse JSON APIs (PeerTube, Odysee).
- **V8** (``STPyV8``): what Grayjay itself runs. Required by plugins
  that bundle browser-grade JavaScript or build code at runtime —
  YouTube does both (a bundled JSDOM whose regexes QuickJS's stricter
  parser rejects, and ``new Function`` to assemble the signature
  decryptor, where QuickJS hits an internal codegen bug).

Neither engine is patched and no plugin source is rewritten; picking the
right engine is the host's job.

On ``eval``: running plugin JavaScript *is* this module's purpose, and
these ``eval`` calls are the JS engine's own — not Python's. The
security boundary is the engine sandbox, which has no filesystem, no
process access, and no network of its own: the only way out is the
host's ``__host_*`` bridges, and the HTTP bridge enforces the plugin's
declared ``allowUrls`` allowlist. Plugins are installed only by explicit
user action (a config URL the user chooses), which is the same trust
model Grayjay itself uses.
"""
from __future__ import annotations

from typing import Callable


class Engine:
    """Common surface: install bridges, eval source, read values back."""

    name = "engine"

    def bind(self, name: str, fn: Callable) -> None:
        raise NotImplementedError

    def eval(self, source: str):
        raise NotImplementedError

    def close(self) -> None:
        pass


class QuickJSEngine(Engine):
    name = "quickjs"

    def __init__(self, memory_limit_mb: int = 256):
        import quickjs

        self.ctx = quickjs.Context()
        try:
            self.ctx.set_memory_limit(memory_limit_mb * 1024 * 1024)
        except Exception:
            pass
        # No engine time limit: quickjs refuses Python callbacks while one
        # is set, and every bridge call is a Python callback. Wall-clock
        # bounding lives in the provider's worker thread instead.

    def bind(self, name: str, fn: Callable) -> None:
        self.ctx.add_callable(name, fn)

    def eval(self, source: str):
        return self.ctx.eval(source)


class V8Engine(Engine):
    """STPyV8. Bridges are methods on the global JSClass instance."""

    name = "v8"

    def __init__(self, memory_limit_mb: int = 256):
        import STPyV8

        self._stpyv8 = STPyV8
        self._bridges: dict[str, Callable] = {}
        bridges = self._bridges

        class _Globals(STPyV8.JSClass):
            """Dispatches JS calls to the registered Python bridges."""

            def __getattr__(self, item):
                if item in bridges:
                    return bridges[item]
                raise AttributeError(item)

        self._globals = _Globals()
        self.ctx = STPyV8.JSContext(self._globals)
        self.ctx.enter()

    def bind(self, name: str, fn: Callable) -> None:
        self._bridges[name] = fn
        # Also set it directly: V8 resolves plain globals faster than
        # going through __getattr__, and some engines cache lookups.
        try:
            setattr(self._globals, name, fn)
        except Exception:
            pass

    def eval(self, source: str):
        return self.ctx.eval(source)

    def close(self) -> None:
        try:
            self.ctx.leave()
        except Exception:
            pass


#: Preference order for ``engine="auto"``. QuickJS leads because it is
#: stable here: it runs the API-shaped plugins (PeerTube, Odysee) end to
#: end. V8 parses everything QuickJS can't (YouTube's bundled JSDOM, its
#: runtime-built signature decryptor) and gets that plugin as far as
#: "remote solver success" — but the current STPyV8 wheel fails to
#: initialize ICU and destabilizes the process, so it stays opt-in
#: (``engine="v8"``) until that upstream packaging issue is resolved.
_ENGINES = {"quickjs": QuickJSEngine, "v8": V8Engine}


#: Import name per engine — probed instead of instantiated, since a
#: broken native engine build can take the whole process down.
_MODULES = {"quickjs": "quickjs", "v8": "STPyV8"}


def available() -> list[str]:
    """Engine names importable in this environment, preferred first."""
    import importlib.util
    return [name for name in _ENGINES
            if importlib.util.find_spec(_MODULES[name]) is not None]


def make_engine(preference: str = "auto", **kwargs) -> Engine:
    """Instantiate an engine by name, or the best available one."""
    if preference != "auto":
        cls = _ENGINES.get(preference)
        if cls is None:
            raise ValueError(f"unknown engine {preference!r}")
        return cls(**kwargs)
    last: Exception | None = None
    for cls in _ENGINES.values():
        try:
            return cls(**kwargs)
        except Exception as e:
            last = e
    raise RuntimeError(
        "no JavaScript engine available — install suite-providers[grayjay] "
        f"(last error: {last})")
