"""Rota da faixa individual: dados do Spotify + BPM e áudio do Deezer."""
import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import enrichment_store
from .auth import get_valid_access_token
from .cache import track_detail_cache
from .deezer_client import buscar_faixa, get_preview_url
from .lastfm_client import get_artist_tags, get_track_tags
from .models import SearchHit, TrackDetail
from .playlists import _spotify_error, account_track_ids
from .spotify_client import SpotifyClient
from .vector_store import similar_to_track

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


async def build_track_detail(access_token: str, track_id: str) -> TrackDetail:
    """Monta o detalhe de uma faixa — usado pela rota HTTP e pelo chat.

    Uma faixa custa três chamadas externas (Spotify, Last.fm x2, Deezer) e os
    metadados não são por usuário, então o resultado é cacheado por id. Em
    desenvolvimento isso importa mais do que parece: o `StrictMode` do React
    monta cada efeito duas vezes, e sem o cache toda visita à página da faixa
    batia duas vezes no Spotify.
    """
    cached = track_detail_cache.get(track_id)
    if cached is not None:
        return cached

    async with httpx.AsyncClient(timeout=20.0) as client:
        # Faixa que já passou por uma análise de playlist tem os metadados no
        # banco: abrir a página dela não custa nada no Spotify.
        faixa = await asyncio.to_thread(enrichment_store.get_spotify_track, track_id)
        if faixa is None:
            # Pelo SpotifyClient, que respeita o bloqueio; por fora dele esta rota
            # continuava chamando o Spotify durante um bloqueio.
            faixa = _campos_usados(await SpotifyClient(access_token).get_track(client, track_id))
            await asyncio.to_thread(enrichment_store.put_spotify_tracks, [faixa])
        artistas = [a["name"] for a in (faixa.get("artists") or []) if a and a.get("name")]
        nome = faixa.get("name") or "(sem título)"
        principal = artistas[0] if artistas else ""

        deezer, tags, artist_tags = await _buscar_em_paralelo(
            client, principal, nome, faixa.get("duration_ms")
        )

    album = faixa.get("album") or {}
    imagens = album.get("images") or []

    detail = TrackDetail(
        track_id=faixa.get("id", track_id),
        name=nome,
        artists=artistas,
        album=album.get("name"),
        image=imagens[0]["url"] if imagens else None,
        duration_ms=faixa.get("duration_ms") or 0,
        spotify_url=(faixa.get("external_urls") or {}).get("spotify"),
        tags=tags,
        artist_tags=artist_tags,
        bpm=(deezer or {}).get("bpm"),
        preview_url=(deezer or {}).get("preview_url"),
        deezer_url=(deezer or {}).get("deezer_url"),
        match_confidence=(deezer or {}).get("confianca"),
        matched_title=(deezer or {}).get("titulo_encontrado"),
    )
    track_detail_cache[track_id] = detail
    return detail


def _campos_usados(faixa: dict) -> dict:
    """Só o que o app lê do objeto de faixa — o mesmo recorte que a listagem de
    faixas de playlist pede ao Spotify, para as duas origens guardarem igual."""
    album = faixa.get("album") or {}
    return {
        "id": faixa.get("id"),
        "name": faixa.get("name"),
        "duration_ms": faixa.get("duration_ms"),
        "popularity": faixa.get("popularity"),
        "explicit": faixa.get("explicit"),
        "external_urls": faixa.get("external_urls"),
        "album": {k: album.get(k) for k in ("name", "images", "release_date")},
        "artists": [{"id": a.get("id"), "name": a.get("name")} for a in faixa.get("artists") or [] if a],
    }


@router.get("/preview/{deezer_id}")
async def track_preview(deezer_id: int, request: Request):
    """A URL atual da prévia de 30s no Deezer.

    As análises guardadas não levam a prévia: ela é uma URL assinada que expira
    em minutos. O player pede esta rota na hora do play, com o id do Deezer que
    a faixa guarda."""
    await get_valid_access_token(request)
    async with httpx.AsyncClient(timeout=15.0) as client:
        url = await get_preview_url(client, deezer_id)
    if not url:
        raise HTTPException(status_code=404, detail="Esta faixa não tem prévia no Deezer.")
    return {"preview_url": url}


@router.get("/{track_id}", response_model=TrackDetail)
async def track_detail(track_id: str, request: Request):
    """Tudo que a página da faixa precisa, resolvido a partir do id do Spotify."""
    token = await get_valid_access_token(request)
    try:
        return await build_track_detail(token, track_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Faixa não encontrada") from exc
        raise _spotify_error(exc) from exc


@router.get("/{track_id}/similar", response_model=list[SearchHit])
async def track_similar(track_id: str, request: Request, limit: int = 8):
    """Faixas parecidas com esta, dentro do que já foi indexado.

    Devolve lista vazia se a faixa ainda não entrou no índice — o índice só
    cresce quando você analisa a playlist que a contém.
    """
    await get_valid_access_token(request)
    # Só entre as faixas desta conta: o índice é compartilhado entre contas.
    return await similar_to_track(track_id, limite=limit, track_ids=await account_track_ids(request))


async def _buscar_em_paralelo(client, artista: str, titulo: str, duracao_ms):
    deezer, tags, artist_tags = await asyncio.gather(
        buscar_faixa(client, artista, titulo, duracao_ms),
        get_track_tags(client, artista, titulo),
        get_artist_tags(client, artista),
        return_exceptions=True,
    )
    return (
        deezer if isinstance(deezer, dict) else None,
        tags if isinstance(tags, list) else [],
        artist_tags if isinstance(artist_tags, list) else [],
    )
