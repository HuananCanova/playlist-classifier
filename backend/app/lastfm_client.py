"""Last.fm tag lookups — the app's only genre source.

Spotify removed the `genres` field from artist objects in its 2026 API changes, so
both levels now come from Last.fm: `artist.getTopTags` gives the broad genre and
`track.getTopTags` the granular subgenre.
"""
import html
import re

import httpx

from .cache import artist_info_cache, artist_tags_cache, track_tags_cache
from .config import get_settings

BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Tags that show up constantly on Last.fm but describe listening behaviour,
# not genre/style — filtered out so they don't pollute subgenre charts.
NOISE_TAGS = {
    "seen live", "favorite", "favorites", "favourite", "favourites", "awesome",
    "love", "loved", "beautiful", "amazing", "good", "great", "cool", "best",
    "spotify", "albums i own", "under 2000 listeners", "00s", "10s", "20s",
    "30s", "40s", "50s", "60s", "70s", "80s", "90s",
}


def _is_genre_like(tag: str) -> bool:
    lower = tag.lower().strip()
    if not lower or lower in NOISE_TAGS:
        return False
    if lower.isdigit():
        return False
    return True


async def _get_top_tags(
    client: httpx.AsyncClient, params: dict, limit: int, exclude: str = ""
) -> list[str]:
    settings = get_settings()
    try:
        resp = await client.get(
            BASE_URL,
            params={**params, "api_key": settings.lastfm_api_key, "format": "json", "autocorrect": 1},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []

    tags_data = (data.get("toptags") or {}).get("tag") or []
    if isinstance(tags_data, dict):  # Last.fm returns a dict instead of a list for a single tag
        tags_data = [tags_data]

    # Listeners often tag a track with the artist's own name — not a genre.
    excluded = exclude.lower().strip()
    return [
        t["name"]
        for t in tags_data
        if _is_genre_like(t.get("name", "")) and t["name"].lower().strip() != excluded
    ][:limit]


async def get_track_tags(client: httpx.AsyncClient, artist: str, track: str, limit: int = 5) -> list[str]:
    # Local files and unavailable items come back without a name; nothing to look up.
    if not artist or not track:
        return []

    cache_key = f"{artist.lower()}::{track.lower()}"
    if cache_key in track_tags_cache:
        return track_tags_cache[cache_key]

    tags = await _get_top_tags(
        client, {"method": "track.getTopTags", "artist": artist, "track": track}, limit, exclude=artist
    )
    track_tags_cache[cache_key] = tags
    return tags


async def get_artist_tags(client: httpx.AsyncClient, artist: str, limit: int = 3) -> list[str]:
    """Broad genre for an artist — the replacement for Spotify's removed `genres` field."""
    if not artist:
        return []

    cache_key = artist.lower()
    if cache_key in artist_tags_cache:
        return artist_tags_cache[cache_key]

    tags = await _get_top_tags(client, {"method": "artist.getTopTags", "artist": artist}, limit)
    artist_tags_cache[cache_key] = tags
    return tags


def _clean_bio(raw: str) -> str:
    """A bio do Last.fm vem com HTML e um rodapé de link "Read more on Last.fm".

    O rodapé não é biografia — é navegação, e apareceria colado ao texto como se
    fosse parte dele. O resto das tags é removido porque a página mostra o texto
    puro, não HTML vindo de terceiros.
    """
    text = re.split(r"<a\s+href=[^>]*>Read more on Last\.fm", raw, maxsplit=1)[0]
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def get_artist_info(client: httpx.AsyncClient, artist: str) -> dict:
    """Biografia, audiência, tags e artistas parecidos — tudo do `artist.getInfo`.

    Uma chamada só cobre o que a página do artista precisa do Last.fm. Devolve
    um dicionário vazio de campos quando o artista não existe lá: a página do
    artista continua válida só com o que veio do Spotify.
    """
    empty = {"bio": None, "listeners": None, "playcount": None, "url": None, "tags": [], "similar": []}
    if not artist:
        return empty

    cache_key = artist.lower()
    if cache_key in artist_info_cache:
        return artist_info_cache[cache_key]

    settings = get_settings()
    try:
        resp = await client.get(
            BASE_URL,
            params={
                "method": "artist.getInfo",
                "artist": artist,
                "api_key": settings.lastfm_api_key,
                "format": "json",
                "autocorrect": 1,
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("artist") or {}
    except (httpx.HTTPError, ValueError):
        return empty

    stats = data.get("stats") or {}
    bio_summary = ((data.get("bio") or {}).get("summary") or "").strip()

    def _int(value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    info = {
        "bio": _clean_bio(bio_summary) or None,
        "listeners": _int(stats.get("listeners")),
        "playcount": _int(stats.get("playcount")),
        "url": data.get("url") or None,
        "tags": [
            t["name"]
            for t in ((data.get("tags") or {}).get("tag") or [])
            if isinstance(t, dict) and _is_genre_like(t.get("name", ""))
        ][:8],
        "similar": [
            {"name": a.get("name"), "url": a.get("url")}
            for a in ((data.get("similar") or {}).get("artist") or [])
            if isinstance(a, dict) and a.get("name")
        ][:8],
    }
    artist_info_cache[cache_key] = info
    return info
