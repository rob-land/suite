"""PlaybackMixin — stream URL, progress reporting, watched state,
next-episode discovery."""

import logging
from typing import Any

from ...media import ContentType, MediaItem, StreamInfo
from ..base import ProviderAuthError, ProviderError
from ._helpers import INCLUDE_FIELDS, seconds_to_ticks

log = logging.getLogger(__name__)


class PlaybackMixin:
    async def get_next_episode(
        self, item: MediaItem, credentials: dict[str, Any] | None,
    ) -> MediaItem | None:
        if item.content_type is not ContentType.EPISODE or not item.parent_id:
            return None
        user_id = self._user_id(credentials)
        # Pull the show's full episode list and find what follows the
        # current one. Cheaper than a per-call NextUp query and keeps
        # behavior predictable across season boundaries.
        try:
            data = await self._get(
                f"/Shows/{item.parent_id}/Episodes",
                credentials,
                params={"UserId": user_id, "Fields": INCLUDE_FIELDS},
            )
        except ProviderError:
            return None
        episodes = (data or {}).get("Items", []) or []
        for idx, jf in enumerate(episodes):
            if jf.get("Id") == item.provider_item_id:
                if idx + 1 < len(episodes):
                    return self._make_item(episodes[idx + 1])
                return None
        return None

    async def get_stream_url(
        self, item: MediaItem, credentials: dict[str, Any] | None,
    ) -> StreamInfo:
        creds = credentials or {}
        token = creds.get("access_token")
        if not token:
            raise ProviderAuthError("no Jellyfin token")
        # Use the simple ?static=true direct-stream URL where possible.
        # Real direct-play decisioning would call /Items/{id}/PlaybackInfo
        # and pick a media source — leave that as a follow-up.
        url = (
            f"{self.server_url}/Videos/{item.provider_item_id}/stream"
            f"?static=true&api_key={token}"
        )
        start = item.progress_seconds or 0.0
        if start and item.runtime_seconds:
            # Don't resume right at the end.
            if start >= 0.95 * item.runtime_seconds:
                start = 0.0
        # Carry the item's stereo hint so 3D-configured players
        # (zoetrope) can pick the right output path; 2D players ignore it.
        return StreamInfo(url=url, start_offset=start, stereo=item.stereo)

    async def report_progress(
        self, item: MediaItem, position_seconds: float,
        credentials: dict[str, Any] | None,
        completed: bool = False,
    ) -> None:
        body = {
            "ItemId": item.provider_item_id,
            "PositionTicks": seconds_to_ticks(position_seconds),
            "IsPaused": False,
            "PlayMethod": "DirectStream",
        }
        path = "/Sessions/Playing/Stopped" if completed else "/Sessions/Playing/Progress"
        try:
            await self._post(path, credentials, json=body)
        except ProviderError:
            log.exception("jellyfin progress report failed")

    async def set_watched(
        self, item: MediaItem, watched: bool,
        credentials: dict[str, Any] | None,
    ) -> None:
        try:
            user_id = self._user_id(credentials)
        except ProviderError:
            log.exception("jellyfin set_watched: no user id")
            return
        path = f"/Users/{user_id}/PlayedItems/{item.provider_item_id}"
        try:
            if watched:
                await self._post(path, credentials)
            else:
                await self._delete(path, credentials)
        except ProviderError:
            log.exception("jellyfin set_watched failed")
