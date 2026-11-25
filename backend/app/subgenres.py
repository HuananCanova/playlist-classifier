"""Rotas de subgênero: o enriquecimento opcional do acervo (e o que vier depois).

Nada aqui chama o Spotify além da listagem de playlists que o perfil já usa
(em cache); o job em si só fala com Last.fm e Deezer.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Request

from . import enrichment_job, profile_store, subgenre_library
from .auth import get_valid_access_token
from .playlists import account_key, get_playlist_summaries

router = APIRouter(prefix="/api/subgenres", tags=["subgenres"])


async def _digests(request: Request) -> dict[str, dict]:
    """Os resumos guardados das playlists da conta. Levanta 429 como o perfil
    quando a listagem não está em cache e o Spotify está bloqueado."""
    playlists = await get_playlist_summaries(request)

    def carregar() -> dict[str, dict]:
        carregados = {p.id: profile_store.load(p.id) for p in playlists if p.track_count}
        return {pid: d for pid, d in carregados.items() if d}

    return await asyncio.to_thread(carregar)


@router.get("/enrich")
async def enrich_status(request: Request):
    """Progresso do job, com quantas faixas ainda faltam."""
    await get_valid_access_token(request)
    account = account_key(request)
    try:
        digests = await _digests(request)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        return enrichment_job.progress_dict(account)  # sem listagem: o que o job já sabe
    pending = len(await asyncio.to_thread(enrichment_job.pending_tracks, digests))
    return enrichment_job.progress_dict(account, pending)


@router.post("/enrich")
async def start_enrich(request: Request):
    """Começa o enriquecimento; com um job já rodando devolve o progresso dele."""
    await get_valid_access_token(request)
    account = account_key(request)
    digests = await _digests(request)  # 429 sobe daqui
    await enrichment_job.start(account, digests)
    return enrichment_job.progress_dict(account)


@router.delete("/enrich")
async def stop_enrich(request: Request):
    """Para o job. A evidência já buscada fica guardada."""
    await get_valid_access_token(request)
    account = account_key(request)
    await enrichment_job.cancel(account)
    return enrichment_job.progress_dict(account)


@router.get("")
async def library(request: Request):
    """Os subgêneros do acervo com quantas faixas cada um tem."""
    await get_valid_access_token(request)
    return subgenre_library.library_subgenres(await _digests(request))


# Depois de /enrich: o parâmetro de caminho engoliria a rota fixa.
@router.get("/{name}")
async def subgenre_page(name: str, request: Request):
    """Faixas de um subgênero: as classificadas como ele e as que puxam para ele."""
    await get_valid_access_token(request)
    playlists = await get_playlist_summaries(request)
    digests = await _digests(request)
    page = subgenre_library.subgenre_tracks(digests, playlists, name)
    if page is None:
        raise HTTPException(status_code=404, detail="Subgênero desconhecido.")
    return page
