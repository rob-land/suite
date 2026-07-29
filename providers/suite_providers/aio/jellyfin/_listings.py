"""ListingsMixin — search, library, continue-watching, episodes,
completed, by-genre, next-up, recently-added."""

from typing import Any

from ...media import ContentType, MediaItem
from ..base import ProviderError
from ._helpers import INCLUDE_FIELDS, LIBRARY_TYPE_FILTER


class ListingsMixin:
    async def search(
        self, query: str, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
    ) -> list[MediaItem]:
        if not query.strip():
            return []
        user_id = self._user_id(credentials)
        params = {
            "searchTerm": query,
            "IncludeItemTypes": "Movie,Series,Episode,MusicAlbum,MusicArtist",
            "Recursive": "true",
            "Limit": 50,
            "Fields": INCLUDE_FIELDS,
        }
        data = await self._get(f"/Users/{user_id}/Items",
                               credentials, params=params)
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def list_library(
        self, content_type: ContentType,
        credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 60,
    ) -> list[MediaItem]:
        user_id = self._user_id(credentials)
        jf_type = LIBRARY_TYPE_FILTER.get(content_type)
        if jf_type is None:
            return []
        params = {
            "IncludeItemTypes": jf_type,
            "Recursive": "true",
            "Limit": limit,
            "SortBy": "DateCreated,SortName",
            "SortOrder": "Descending",
            "Fields": INCLUDE_FIELDS,
        }
        data = await self._get(f"/Users/{user_id}/Items",
                               credentials, params=params)
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def get_continue_watching(
        self, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 12,
    ) -> list[MediaItem]:
        user_id = self._user_id(credentials)
        params = {
            "Limit": limit,
            "Recursive": "true",
            "Fields": INCLUDE_FIELDS,
            "MediaTypes": "Video",
        }
        data = await self._get(f"/Users/{user_id}/Items/Resume",
                               credentials, params=params)
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def get_episodes(
        self, show: MediaItem, credentials: dict[str, Any] | None,
    ) -> list[MediaItem]:
        user_id = self._user_id(credentials)
        params = {
            "UserId": user_id,
            "Fields": INCLUDE_FIELDS,
        }
        data = await self._get(
            f"/Shows/{show.provider_item_id}/Episodes",
            credentials, params=params,
        )
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def completed_items(
        self, credentials: dict[str, Any] | None,
        limit: int = 200,
    ) -> list[MediaItem]:
        try:
            user_id = self._user_id(credentials)
        except ProviderError:
            return []
        params = {
            "Recursive": "true",
            "Filters": "IsPlayed",
            "IncludeItemTypes": "Movie,Series",
            "Limit": limit,
            "Fields": INCLUDE_FIELDS,
        }
        try:
            data = await self._get(
                f"/Users/{user_id}/Items", credentials, params=params,
            )
        except ProviderError:
            return []
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def list_by_genre(
        self, genre: str, content_type: ContentType,
        credentials: dict[str, Any] | None,
        limit: int = 24,
    ) -> list[MediaItem]:
        try:
            user_id = self._user_id(credentials)
        except ProviderError:
            return []
        jf_type = LIBRARY_TYPE_FILTER.get(content_type)
        if jf_type is None:
            return []
        params = {
            "Recursive": "true",
            "IncludeItemTypes": jf_type,
            "Genres": genre,
            "Limit": limit,
            "SortBy": "Random",
            "Fields": INCLUDE_FIELDS,
        }
        try:
            data = await self._get(
                f"/Users/{user_id}/Items", credentials, params=params,
            )
        except ProviderError:
            return []
        return [self._make_item(it) for it in (data or {}).get("Items", [])]

    async def next_up_for(
        self, show: MediaItem, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        if show.content_type is not ContentType.SHOW:
            return None
        try:
            user_id = self._user_id(credentials)
        except ProviderError:
            return None
        params = {
            "UserId": user_id,
            "SeriesId": show.provider_item_id,
            "Limit": 1,
            "Fields": INCLUDE_FIELDS,
        }
        try:
            data = await self._get("/Shows/NextUp", credentials,
                                   params=params)
        except ProviderError:
            return None
        items = (data or {}).get("Items") or []
        if not items:
            return None
        return self._make_item(items[0])

    async def get_recently_added(
        self, credentials: dict[str, Any] | None,
        max_content_rating_index: int | None = None,
        limit: int = 24,
    ) -> list[MediaItem]:
        user_id = self._user_id(credentials)
        params = {
            "Limit": limit,
            "Fields": INCLUDE_FIELDS,
            "IncludeItemTypes": "Movie,Series,Episode,MusicAlbum",
        }
        try:
            data = await self._get(
                f"/Users/{user_id}/Items/Latest",
                credentials, params=params,
            )
        except ProviderError:
            return []
        # /Latest returns a flat list (not wrapped in {"Items": [...]}).
        if isinstance(data, list):
            return [self._make_item(it) for it in data]
        return [self._make_item(it) for it in (data or {}).get("Items", [])]
