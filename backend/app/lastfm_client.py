"""Last.fm tag lookups — the app's only genre source.

Spotify removed the `genres` field from artist objects in its 2026 API changes, so
both levels now come from Last.fm: `artist.getTopTags` gives the broad genre and
`track.getTopTags` the granular subgenre.

Cada consulta passa por três níveis: cache em memória, banco (enrichment_store,
válido por semanas) e só então a rede. Só respostas de verdade são guardadas —
uma falha de rede devolve lista vazia para quem pediu, mas não fica lembrada.
"""
import asyncio

import httpx

from . import enrichment_store
from .cache import artist_tags_cache, track_tags_cache
from .config import get_settings

BASE_URL = "https://ws.audioscrobbler.com/2.0/"

LASTFM_NOT_FOUND = 6

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
) -> list[str] | None:
    """As tags, ou None se o Last.fm não respondeu (e aí nada deve ser guardado)."""
    settings = get_settings()
    try:
        resp = await client.get(
            BASE_URL,
            params={**params, "api_key": settings.lastfm_api_key, "format": "json", "autocorrect": 1},
            timeout=10.0,
        )
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    # O Last.fm responde erro dentro de um JSON, às vezes com HTTP 200 e às
    # vezes não. Só o 6 ("não existe") é uma resposta de verdade — "não tem
    # tag" — e pode ser guardado. Os outros (29 = limite, 11/16 = fora do ar,
    # 10/26 = chave) são falhas passageiras ou de configuração; guardá-los
    # apagaria as tags da faixa por semanas.
    error = data.get("error")
    if error is not None:
        return [] if error == LASTFM_NOT_FOUND else None
    if resp.status_code != 200:
        return None

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

    stored = await asyncio.to_thread(enrichment_store.get_track_tags, cache_key)
    if stored is not None:
        track_tags_cache[cache_key] = stored
        return stored

    tags = await _get_top_tags(
        client, {"method": "track.getTopTags", "artist": artist, "track": track}, limit, exclude=artist
    )
    if tags is None:
        return []
    track_tags_cache[cache_key] = tags
    await asyncio.to_thread(enrichment_store.put_track_tags, cache_key, tags)
    return tags


async def get_artist_tags(client: httpx.AsyncClient, artist: str, limit: int = 3) -> list[str]:
    """Broad genre for an artist — the replacement for Spotify's removed `genres` field."""
    if not artist:
        return []

    cache_key = artist.lower()
    if cache_key in artist_tags_cache:
        return artist_tags_cache[cache_key]

    stored = await asyncio.to_thread(enrichment_store.get_artist_tags, cache_key)
    if stored is not None:
        artist_tags_cache[cache_key] = stored
        return stored

    tags = await _get_top_tags(client, {"method": "artist.getTopTags", "artist": artist}, limit)
    if tags is None:
        return []
    artist_tags_cache[cache_key] = tags
    await asyncio.to_thread(enrichment_store.put_artist_tags, cache_key, tags)
    return tags
