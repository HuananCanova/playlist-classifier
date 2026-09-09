"""Rota da faixa individual: dados do Spotify + BPM e áudio do Deezer."""
import asyncio

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import get_valid_access_token
from .deezer_client import buscar_faixa
from .lastfm_client import get_artist_tags, get_track_tags
from .models import TrackDetail
from .spotify_client import BASE_URL as SPOTIFY_BASE

router = APIRouter(prefix="/api/tracks", tags=["tracks"])


async def build_track_detail(access_token: str, track_id: str) -> TrackDetail:
    """Monta o detalhe de uma faixa — usado pela rota HTTP e pelo chat."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{SPOTIFY_BASE}/tracks/{track_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 404:
            raise httpx.HTTPStatusError(
                "Faixa não encontrada", request=resp.request, response=resp
            )
        resp.raise_for_status()

        faixa = resp.json()
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
    return detail


@router.get("/{track_id}", response_model=TrackDetail)
async def track_detail(track_id: str, request: Request):
    """Tudo que a página da faixa precisa, resolvido a partir do id do Spotify."""
    token = await get_valid_access_token(request)
    try:
        return await build_track_detail(token, track_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Faixa não encontrada") from exc
        raise HTTPException(status_code=502, detail="Erro na API do Spotify") from exc


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
