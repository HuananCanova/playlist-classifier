"""Rota da busca semântica sobre as faixas indexadas."""
import logging

from fastapi import APIRouter, HTTPException, Query, Request

import asyncio

from . import indexer
from .auth import get_valid_access_token
from .config import get_settings
from .models import IndexStatus, SearchHit, SearchStatus
from .playlists import account_key, account_track_ids, get_playlist_summaries
from .spotify_client import global_block_remaining
from .vector_store import search as vector_search
from .vector_store import stats as vector_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[SearchHit])
async def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200, description="A pergunta em linguagem natural."),
    limit: int = Query(default=20, ge=1, le=50),
):
    """Busca semântica em tudo que esta conta já analisou.

    O índice é compartilhado entre as contas, então a busca se limita às faixas
    das playlists desta conta — nunca devolve faixas de outra pessoa.
    """
    await get_valid_access_token(request)
    return await vector_search(q, limite=limit, track_ids=await account_track_ids(request))


@router.get("/status", response_model=SearchStatus)
async def status(request: Request):
    """Cobertura do índice: faixas dentro, e quantas playlists faltam.

    O frontend usa isso para explicar um resultado vazio. "Nada encontrado" e
    "ainda não olhei essa playlist" são coisas diferentes, e sem esse número a
    tela não tem como distinguir as duas.
    """
    await get_valid_access_token(request)
    dados = await vector_stats(await account_track_ids(request))
    try:
        # Listagem em cache (memória, depois disco): consultar a cobertura não
        # custa chamada ao Spotify, por mais que a tela seja recarregada.
        playlists = [p.model_dump() for p in await get_playlist_summaries(request)]
    except HTTPException:
        return SearchStatus(indexed_tracks=dados["faixas_indexadas"], blocked_seconds=global_block_remaining())
    return SearchStatus(
        indexed_tracks=dados["faixas_indexadas"],
        blocked_seconds=global_block_remaining(),
        **await asyncio.to_thread(indexer.coverage, playlists),
    )


@router.post("/index", response_model=IndexStatus)
async def start_index(request: Request, auto: bool = False):
    """Varre as playlists ainda não indexadas.

    `auto=true` é a chamada que o app dispara sozinho ao abrir; ela respeita a
    configuração `AUTO_INDEX` e não faz nada se estiver desligada. Sem o
    parâmetro, é uma ação explícita do usuário e sempre roda.
    """
    await get_valid_access_token(request)

    if auto and not get_settings().auto_index:
        return IndexStatus(**indexer.progress_dict(account_key(request)))

    # A varredura sobrevive à requisição, e um access token expira em uma hora.
    # O refresh token é o que permite renovar durante o trabalho.
    refresh_token = request.session.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Sessão sem refresh token; entre de novo.")

    playlists = [p.model_dump() for p in await get_playlist_summaries(request)]
    await indexer.start(account_key(request), refresh_token, playlists)
    return IndexStatus(**indexer.progress_dict(account_key(request)))


@router.get("/index", response_model=IndexStatus)
async def index_status(request: Request):
    await get_valid_access_token(request)
    return IndexStatus(**indexer.progress_dict(account_key(request)))


@router.delete("/index", response_model=IndexStatus)
async def stop_index(request: Request):
    """Interrompe a varredura em andamento.

    O que já foi indexado permanece: o estado é gravado playlist a playlist, e
    a próxima varredura recomeça de onde esta parou.
    """
    await get_valid_access_token(request)
    await indexer.cancel(account_key(request))
    return IndexStatus(**indexer.progress_dict(account_key(request)))
