"""MatchingMixin — cross-provider canonical-id lookup + similar items.

AnyProviderIdEquals is unreliable across Jellyfin versions, so we
build a (scheme, id) → MediaItem index once per hour by paging the
whole movie/series catalog with ProviderIds populated. Lookups are
then local and exact. A TMDB-assisted fallback handles items whose
ProviderIds weren't filled in on this Jellyfin instance.
"""

import logging
from typing import Any

from ...media import MediaItem
from ..base import ProviderError
from ._helpers import INCLUDE_FIELDS

log = logging.getLogger(__name__)


class MatchingMixin:
    _INDEX_TTL_SECONDS = 3600

    async def find_by_canonical_id(
        self, canonical_id: str, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        if not canonical_id or ":" not in canonical_id:
            return None
        scheme, value = canonical_id.split(":", 1)
        index = await self._provider_index(credentials)
        if index is None:
            return None
        return index.get((scheme.lower(), value.lower()))

    async def _provider_index(
        self, credentials: dict[str, Any] | None,
    ) -> dict[tuple[str, str], MediaItem] | None:
        import asyncio
        from time import monotonic
        creds_key = (credentials or {}).get("user_id") or ""
        lock = self.__dict__.setdefault("_index_lock", asyncio.Lock())
        async with lock:
            cached = getattr(self, "_index_cache", None)
            if cached and cached.get("user") == creds_key:
                if monotonic() - cached["at"] < self._INDEX_TTL_SECONDS:
                    return cached["index"]
            built = await self._build_provider_index(credentials, creds_key)
            # Cache failures briefly so 24 concurrent probes don't all
            # serially retry a slow / unreachable server. 60s is short
            # enough that recovery feels prompt; long enough to avoid
            # the stampede.
            if built is None:
                self._index_cache = {  # type: ignore[attr-defined]
                    "user": creds_key,
                    "at": monotonic() - (self._INDEX_TTL_SECONDS - 60),
                    "index": {},
                }
                return {}
            return built

    async def _build_provider_index(
        self, credentials: dict[str, Any] | None, creds_key: str,
    ) -> dict[tuple[str, str], MediaItem] | None:
        try:
            user_id = self._user_id(credentials)
        except ProviderError:
            return None
        index: dict[tuple[str, str], MediaItem] = {}

        # Slim Fields: only what _make_item actually consumes plus the
        # ProviderIds we're keying by. Genres/People/Chapters are
        # heavy and unused in the lookup-result MediaItem.
        slim_fields = (
            "Overview,UserData,RunTimeTicks,ProductionYear,"
            "OfficialRating,ProviderIds,SeriesId,ParentIndexNumber,"
            "IndexNumber,SeriesName"
        )
        # Page through the library so a single request doesn't have
        # to materialize thousands of items at once.
        page_size = 500
        offset = 0
        while True:
            params = {
                "Recursive": "true",
                "IncludeItemTypes": "Movie,Series",
                "Fields": slim_fields,
                "Limit": page_size,
                "StartIndex": offset,
            }
            try:
                data = await self._get(
                    f"/Users/{user_id}/Items", credentials, params=params,
                )
            except ProviderError as exc:
                log.debug("provider-index fetch failed: %s", exc)
                return None
            page = (data or {}).get("Items") or []
            for it in page:
                prov_ids = it.get("ProviderIds") or {}
                for k, v in prov_ids.items():
                    if not v:
                        continue
                    index[(k.lower(), str(v).lower())] = self._make_item(it)
            if len(page) < page_size:
                break
            offset += page_size
            if offset > 50_000:  # sanity stop
                break
        log.debug("provider-index built: %d ids", len(index))
        self._index_cache = {  # type: ignore[attr-defined]
            "user": creds_key,
            "at": __import__("time").monotonic(),
            "index": index,
        }
        return index

    async def _search_by_canonical(
        self, scheme: str, value: str,
        credentials: dict[str, Any] | None, user_id: str,
    ) -> MediaItem | None:
        from .. import metadata as _md
        token = _md.tmdb_token()
        if not token:
            log.debug("avail pass2 %s:%s no tmdb token", scheme, value)
            return None
        client = _md.TMDBClient(token)
        try:
            tries: list[tuple[str, str]] = []
            if scheme.lower() == "tmdb":
                tries = [("movie", value), ("tv", value)]
            elif scheme.lower() == "tvdb":
                tries = [("tv", value)]
            title: str | None = None
            year: int | None = None
            for k, v in tries:
                try:
                    detail = (await client.movie(v)) if k == "movie" \
                        else await client.tv(v)
                except Exception:
                    detail = None
                if detail:
                    title = detail.get("title") or detail.get("name")
                    date = (detail.get("release_date")
                            or detail.get("first_air_date") or "")
                    if len(date) >= 4:
                        try:
                            year = int(date[:4])
                        except ValueError:
                            year = None
                    if title:
                        log.debug("avail pass2 %s:%s tmdb resolved: %r (%s)",
                                  scheme, value, title, year)
                        break
        finally:
            await client.close()

        if not title:
            log.debug("avail pass2 %s:%s no tmdb title", scheme, value)
            return None
        params = {
            "Recursive": "true",
            "SearchTerm": title,
            "IncludeItemTypes": "Movie,Series",
            "Limit": 5,
            "Fields": INCLUDE_FIELDS,
        }
        if year:
            params["Years"] = str(year)
        try:
            data = await self._get(
                f"/Users/{user_id}/Items", credentials, params=params,
            )
        except ProviderError as exc:
            log.debug("avail pass2 %s:%s jf-error: %s", scheme, value, exc)
            return None
        items = (data or {}).get("Items") or []
        log.debug(
            "avail pass2 %s:%s search %r year=%s -> %d hits: %s",
            scheme, value, title, year, len(items),
            [(it.get("Name"), it.get("ProductionYear")) for it in items],
        )
        norm_title = title.lower()
        for it in items:
            it_title = (it.get("Name") or "").lower()
            it_year = it.get("ProductionYear")
            if it_title == norm_title and (
                year is None or it_year == year
            ):
                return self._make_item(it)
        return None

    async def get_similar(
        self, item: MediaItem, credentials: dict[str, Any] | None,
        limit: int = 12,
    ) -> list[MediaItem]:
        user_id = self._user_id(credentials)
        params = {
            "UserId": user_id,
            "Limit": limit,
            "Fields": INCLUDE_FIELDS,
        }
        try:
            data = await self._get(
                f"/Items/{item.provider_item_id}/Similar",
                credentials, params=params,
            )
        except ProviderError:
            return []
        return [self._make_item(it) for it in (data or {}).get("Items", [])]
