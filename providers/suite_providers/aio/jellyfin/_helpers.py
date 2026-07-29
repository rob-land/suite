"""Stateless helpers + constants for the Jellyfin provider mixins."""

import socket
import uuid

from ...models import StereoHint
from ...naming import jellyfin_format_to_stereo, video_stereo_hint

from ...media import ContentRating, ContentType

# Mapping Jellyfin's `Type` field to our enum.
TYPE_MAP = {
    "Movie": ContentType.MOVIE,
    "Series": ContentType.SHOW,
    "Season": ContentType.SEASON,
    "Episode": ContentType.EPISODE,
    "MusicAlbum": ContentType.MUSIC_ALBUM,
    "Audio": ContentType.MUSIC_TRACK,
    "MusicArtist": ContentType.MUSIC_ARTIST,
}

INCLUDE_FIELDS = (
    "PrimaryImageAspectRatio,Overview,UserData,RunTimeTicks,"
    "ProductionYear,OfficialRating,ProviderIds,SeriesId,"
    "ParentIndexNumber,IndexNumber,SeriesName,Genres,People,Chapters,"
    "Video3DFormat,Path"
)


def stereo_hint(jf: dict) -> StereoHint:
    """Stereo-3D hint for a Jellyfin DTO, in the suite vocabulary.

    ``Video3DFormat`` is authoritative when present (the server parsed
    it from the filename, or a user set it in the metadata editor);
    otherwise fall back to the suite's shared filename rules on the
    item ``Path`` — catches servers that missed the tag.
    """
    hint = jellyfin_format_to_stereo(jf.get("Video3DFormat"))
    if not hint.format.is_stereo:
        named = video_stereo_hint(jf.get("Path") or "")
        if named.format.is_stereo:
            return named
    return hint

LIBRARY_TYPE_FILTER = {
    ContentType.MOVIE: "Movie",
    ContentType.SHOW: "Series",
    ContentType.MUSIC_ALBUM: "MusicAlbum",
    ContentType.MUSIC_ARTIST: "MusicArtist",
}


def _device_id() -> str:
    """Stable per-host device id Jellyfin uses to track sessions."""
    name = socket.gethostname() or "couch"
    # UUID5 over a fixed namespace to stay stable across restarts.
    ns = uuid.UUID("4b8d2f3e-9a1c-4e7d-9c6e-7d3a1c8b2f9e")
    return str(uuid.uuid5(ns, name))


def _client_name() -> str:
    return "Couch"


def _client_version() -> str:
    try:
        from ... import VERSION
        return VERSION
    except Exception:
        return "0.1.0"


def emby_auth_header(token: str | None = None) -> str:
    """Build the X-Emby-Authorization header Jellyfin expects."""
    parts = [
        f'MediaBrowser Client="{_client_name()}"',
        'Device="Couch"',
        f'DeviceId="{_device_id()}"',
        f'Version="{_client_version()}"',
    ]
    if token:
        parts.append(f'Token="{token}"')
    return ", ".join(parts)


def ticks_to_seconds(ticks: int | float | None) -> float | None:
    if ticks is None:
        return None
    return float(ticks) / 10_000_000.0


def seconds_to_ticks(seconds: float) -> int:
    return int(seconds * 10_000_000)


def map_rating(jf_rating: str | None) -> ContentRating | None:
    if not jf_rating:
        return None
    upper = jf_rating.strip().upper().replace(" ", "")
    aliases = {
        "G": ContentRating.G,
        "TVY": ContentRating.TV_Y,
        "TVY7": ContentRating.TV_Y7,
        "TVY7FV": ContentRating.TV_Y7,
        "TVG": ContentRating.TV_G,
        "PG": ContentRating.PG,
        "TVPG": ContentRating.TV_PG,
        "PG13": ContentRating.PG_13,
        "PG-13": ContentRating.PG_13,
        "TV14": ContentRating.TV_14,
        "R": ContentRating.R,
        "TVMA": ContentRating.TV_MA,
        "NC17": ContentRating.NC_17,
        "NC-17": ContentRating.NC_17,
    }
    return aliases.get(upper)
