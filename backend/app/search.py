"""Rota da busca semântica sobre as faixas indexadas."""
import logging

from fastapi import APIRouter, Query, Request

from .auth import get_valid_access_token
from .models import SearchHit, SearchStatus
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
    """Busca semântica em tudo que já foi analisado.

    Exige sessão porque o índice é do acervo do usuário — mesmo que a consulta
    em si não toque no Spotify.
    """
    await get_valid_access_token(request)
    return await vector_search(q, limite=limit)


@router.get("/status", response_model=SearchStatus)
async def status(request: Request):
    """Quantas faixas já entraram no índice.

    O frontend usa isso para explicar um resultado vazio: índice vazio é
    "abra uma playlist primeiro", não "nada encontrado".
    """
    await get_valid_access_token(request)
    dados = await vector_stats()
    return SearchStatus(indexed_tracks=dados["faixas_indexadas"])
