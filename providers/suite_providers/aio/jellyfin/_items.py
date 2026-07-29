"""ItemsMixin — Jellyfin response → MediaItem projection + image URLs."""

from typing import Any

from ...media import ContentType, MediaItem
from ._helpers import TYPE_MAP, map_rating, stereo_hint, ticks_to_seconds


class ItemsMixin:
    def _image_url(self, item: dict[str, Any], image_type: str = "Primary") -> str | None:
        if image_type not in (item.get("ImageTags") or {}):
            if image_type == "Backdrop":
                tags = item.get("BackdropImageTags") or []
                if not tags:
                    return None
                tag = tags[0]
            else:
                return None
        else:
            tag = item["ImageTags"][image_type]
        return (
            f"{self.server_url}/Items/{item['Id']}/Images/{image_type}"
            f"?tag={tag}&quality=90"
        )

    def _make_item(self, jf: dict[str, Any]) -> MediaItem:
        ctype = TYPE_MAP.get(jf.get("Type", ""), ContentType.OTHER)
        provider_ids = jf.get("ProviderIds") or {}
        canonical = None
        if provider_ids.get("Tmdb"):
            canonical = f"tmdb:{provider_ids['Tmdb']}"
        elif provider_ids.get("Tvdb"):
            canonical = f"tvdb:{provider_ids['Tvdb']}"
        user_data = jf.get("UserData") or {}
        progress = ticks_to_seconds(user_data.get("PlaybackPositionTicks"))
        if not progress:
            progress = None
        played_pct = user_data.get("PlayedPercentage")
        last_played = user_data.get("LastPlayedDate")
        title = jf.get("Name") or ""
        extras: dict[str, Any] = {
            "jellyfin_type": jf.get("Type"),
            "source_display_name": self.source_display_name,
        }
        if provider_ids.get("Imdb"):
            extras["imdb_id"] = provider_ids["Imdb"]
        if last_played:
            extras["last_played"] = last_played
        if ctype is ContentType.EPISODE:
            series = jf.get("SeriesName") or ""
            if series:
                extras["series_name"] = series
        people = jf.get("People") or []
        if people:
            cast = [p.get("Name") for p in people
                    if p.get("Type") == "Actor" and p.get("Name")]
            directors = [p.get("Name") for p in people
                         if p.get("Type") == "Director" and p.get("Name")]
            if cast:
                extras["cast"] = cast[:8]
            if directors:
                extras["directors"] = directors[:3]
        return MediaItem(
            provider_id=self.source_id or self.provider_id,
            provider_item_id=jf["Id"],
            title=title,
            content_type=ctype,
            description=jf.get("Overview") or "",
            year=jf.get("ProductionYear"),
            runtime_seconds=int(ticks_to_seconds(jf.get("RunTimeTicks")) or 0)
                or None,
            poster_url=self._image_url(jf, "Primary"),
            backdrop_url=self._image_url(jf, "Backdrop"),
            rating=map_rating(jf.get("OfficialRating")),
            canonical_id=canonical,
            parent_id=jf.get("SeriesId"),
            season_index=jf.get("ParentIndexNumber"),
            episode_index=jf.get("IndexNumber"),
            progress_seconds=progress,
            progress_fraction=(played_pct / 100.0) if played_pct else None,
            genres=list(jf.get("Genres") or []),
            stereo=stereo_hint(jf),
            chapters=[
                {
                    "name": c.get("Name") or "",
                    "start_seconds": ticks_to_seconds(
                        c.get("StartPositionTicks") or 0,
                    ) or 0.0,
                }
                for c in (jf.get("Chapters") or [])
            ],
            extras=extras,
        )
