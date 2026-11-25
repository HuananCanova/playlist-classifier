"""Last.fm tag lookups — the app's only genre source.

Spotify removed the `genres` field from artist objects in its 2026 API changes, so
both levels now come from Last.fm: `artist.getTopTags` gives the broad genre and
`track.getTopTags` the granular subgenre.

Cada consulta passa por três níveis: cache em memória, banco (enrichment_store,
válido por semanas) e só então a rede. Só respostas de verdade são guardadas —
uma falha de rede devolve lista vazia para quem pediu, mas não fica lembrada.

As tags saem daqui COM PESO (`taxonomy.Tag`). O Last.fm devolve um `count` de
0–100 por tag, que media a força relativa dela para aquele artista ou faixa, e
descartá-lo custava caro: "rock" com 100 e "chillwave" com 2 entravam na conta
como votos iguais. Quem classifica (`taxonomy.classify`) usa esse peso.

Descartar tag que não é gênero também não é mais trabalho deste módulo: a
taxonomia tem a lista, por categoria e com o motivo (`taxonomy.yaml`), e ela
cresce sozinha conforme o relatório de cobertura aponta o que falta.
"""
import asyncio

import httpx

from . import enrichment_store
from .cache import artist_tags_cache, track_tags_cache
from .config import get_settings
from .taxonomy import Tag

BASE_URL = "https://ws.audioscrobbler.com/2.0/"

LASTFM_NOT_FOUND = 6


class NoAnswer(list):
    """Lista vazia que quer dizer "o Last.fm não respondeu".

    Para quem só lê tags é uma lista vazia comum; quem guarda evidência
    (`genre_analysis`) a distingue de "respondeu e não há tags" e não grava nada.
    """


async def _get_top_tags(
    client: httpx.AsyncClient, params: dict, limit: int, exclude: str = ""
) -> list[Tag] | None:
    """As tags com peso, ou None se o Last.fm não respondeu (e aí nada deve ser guardado)."""
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
    tags: list[Tag] = []
    for t in tags_data:
        name = (t.get("name") or "").strip()
        if not name or name.lower() == excluded:
            continue
        try:
            weight = float(t.get("count"))
        except (TypeError, ValueError):
            # Sem `count` (acontece em tag recém-criada), vale o mínimo útil:
            # entra na conta, mas não decide sozinha contra uma tag de peso.
            weight = 1.0
        tags.append(Tag(name, weight))
        if len(tags) >= limit:
            break
    return tags


async def get_track_tags(client: httpx.AsyncClient, artist: str, track: str, limit: int = 10) -> list[Tag]:
    """Tags da faixa, com peso. O limite subiu de 5 para 10 porque filtrar passou
    a ser trabalho da taxonomia: antes cada vaga podia ser gasta com "seen live"
    ou um país, e agora as tags que não são gênero saem depois, de graça — a
    requisição ao Last.fm é a mesma, só se aproveita mais dela."""
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
        return NoAnswer()
    track_tags_cache[cache_key] = tags
    await asyncio.to_thread(enrichment_store.put_track_tags, cache_key, tags)
    return tags


async def get_artist_tags(client: httpx.AsyncClient, artist: str, limit: int = 8) -> list[Tag]:
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
        return NoAnswer()
    artist_tags_cache[cache_key] = tags
    await asyncio.to_thread(enrichment_store.put_artist_tags, cache_key, tags)
    return tags
