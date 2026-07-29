"""Async provider layer (moved from couch 2026-07-29).

The full-featured MediaProvider interface + implementations that both
couch (TV shell) and zoetrope (glasses shell) drive. Sync counterparts
in :mod:`suite_providers.provider` remain for probe tooling and the
local-files reference.
"""
from .base import (
    MediaProvider,
    ProviderAuthError,
    ProviderError,
    ProviderUnreachableError,
)
from .jellyfin import JellyfinProvider

__all__ = [
    "JellyfinProvider",
    "MediaProvider",
    "ProviderAuthError",
    "ProviderError",
    "ProviderUnreachableError",
]
