"""Rotas do perfil: estatísticas da conta a partir das playlists acessíveis.

Abrir o perfil não chama o Spotify. O painel é montado com o que já existe:

1. a listagem de playlists (em cache, em memória e em disco);
2. os resumos por playlist em disco (`profile_store`), gravados sempre que uma
   playlist é analisada em qualquer lugar do app;
3. o índice da busca, que dá artistas e estilos do acervo inteiro já indexado.

Completar o que falta é uma ação explícita (`POST /api/profile/build`), feita
pela mesma varredura da busca (`indexer`), com ritmo controlado.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from . import indexer, profile_store
from .auth import get_me, get_valid_access_token, user_key
from .playlists import get_playlist_summaries
from .profile_stats import build_index_stats, build_profile_stats
from .spotify_client import global_block_remaining
from .vector_store import all_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["profile"])

# Estatísticas do índice por tamanho do índice: só recalcula quando entram
# faixas. Por conta, senão o painel de uma mostraria o número da outra.
_index_stats_cache: dict[str, dict] = {}


async def _index_stats(owner: str) -> dict | None:
    try:
        count, metadatas = await all_metadata(owner)
    except Exception:
        # O índice é complemento; se o Chroma falhar, o painel segue sem ele.
        logger.exception("Não consegui ler o índice para o perfil")
        return None
    entrada = _index_stats_cache.get(owner)
    if entrada is None or entrada["count"] != count:
        entrada = {
            "count": count,
            "stats": await asyncio.to_thread(build_index_stats, metadatas),
        }
        _index_stats_cache[owner] = entrada
    return entrada["stats"]


def _snapshot(playlists, owner: str) -> dict:
    """Números gerais, coberturas e estatísticas — tudo síncrono e local."""
    rows = [p.model_dump() for p in playlists]
    non_empty = [p for p in playlists if p.track_count]

    digests = {p.id: profile_store.load(p.id) for p in non_empty}
    fresh = [p for p in non_empty if profile_store.is_fresh(digests[p.id], p.snapshot_id)]
    fresh_ids = {p.id for p in fresh}
    stale = [p for p in non_empty if digests[p.id] and p.id not in fresh_ids]

    largest = max(playlists, key=lambda p: p.track_count, default=None)
    account = indexer.coverage(rows, owner)

    return {
        "overview": {
            "playlists": len(playlists),
            "empty_playlists": len(playlists) - len(non_empty),
            "tracks_listed": sum(p.track_count for p in playlists),
            "largest_playlist": (
                {"id": largest.id, "name": largest.name, "image": largest.image, "tracks": largest.track_count}
                if largest and largest.track_count
                else None
            ),
        },
        "coverage": {
            "playlists_total": len(non_empty),
            "playlists_ready": len(fresh),
            # Resumos de uma versão anterior da playlist entram nas estatísticas
            # (melhor que um buraco) e são refeitos pela varredura.
            "playlists_stale": len(stale),
            "tracks_total": sum(p.track_count for p in non_empty),
            "tracks_ready": sum(p.track_count for p in fresh),
            # O que a varredura faria agora, e quanto custaria no Spotify.
            "pending_playlists": account["pending_playlists"],
            "estimated_calls": account["estimated_calls"],
        },
        # Os resumos velhos também contam: um painel quase certo agora é mais
        # útil do que um painel vazio até a varredura terminar.
        "stats": build_profile_stats(rows, {k: v for k, v in digests.items() if v}),
    }


@router.get("")
async def get_profile(request: Request):
    """O painel com o que já existe. Não dispara varredura nem chama o Spotify
    (a não ser que a listagem em cache tenha expirado)."""
    token = await get_valid_access_token(request)
    user = await get_me(request, token)
    try:
        playlists = await get_playlist_summaries(request)
    except HTTPException as exc:
        # Bloqueado e sem listagem guardada: ainda dá para mostrar o índice.
        if exc.status_code != 429:
            raise
        playlists = []
    owner = user_key(request)
    data, index = await asyncio.gather(
        asyncio.to_thread(_snapshot, playlists, owner), _index_stats(owner)
    )
    return {
        "user": {k: v for k, v in user.items() if k != "fetched_at"},
        **data,
        "index": index,
        "build": indexer.progress_dict(),
        "spotify_blocked_seconds": global_block_remaining(),
    }


@router.get("/build")
async def build_status(request: Request):
    """Só o progresso — o que o painel consulta enquanto a varredura roda."""
    await get_valid_access_token(request)
    return indexer.progress_dict()


@router.post("/build")
async def start_build(request: Request, refresh: bool = False):
    """Analisa as playlists que ainda não têm resumo ou índice, ou que mudaram.

    É a mesma varredura da busca, então pedir pelo perfil e pela busca ao mesmo
    tempo não duplica nada. `refresh=true` relê a listagem do Spotify antes.
    """
    await get_valid_access_token(request)

    # A varredura sobrevive à requisição; o refresh token renova o acesso no meio.
    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Sessão sem refresh token; entre de novo.")

    playlists = await get_playlist_summaries(request, refresh=refresh and not global_block_remaining())
    await indexer.start(
        refresh_token, user_key(request), [p.model_dump() for p in playlists]
    )
    return indexer.progress_dict()


@router.delete("/build")
async def stop_build(request: Request):
    """Para a varredura. O que já foi feito fica em disco."""
    await get_valid_access_token(request)
    await indexer.cancel()
    return indexer.progress_dict()
