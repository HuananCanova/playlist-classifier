"""Routes for listing the user's playlists and analyzing one in detail."""
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import get_valid_access_token
from .genre_analysis import build_playlist_analysis
from .models import PlaylistAnalysis, PlaylistSummary
from .spotify_client import SpotifyClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


def _spotify_error(exc: httpx.HTTPStatusError) -> HTTPException:
    """Traduz uma falha do Spotify em algo que a interface consiga explicar.

    Antes disso qualquer erro subia como 500 com stack trace — inclusive o 429,
    que é temporário e não é culpa do usuário.
    """
    status = exc.response.status_code
    logger.error(
        "Spotify returned %s for %s: %s", status, exc.request.url, exc.response.text[:500]
    )

    if status == 429:
        retry_after = exc.response.headers.get("Retry-After", "")
        return HTTPException(
            status_code=429,
            detail="O Spotify limitou as requisições temporariamente. Tente de novo em instantes.",
            # Repassado para o front conseguir dizer quantos segundos faltam.
            headers={"Retry-After": retry_after} if retry_after else None,
        )
    if status == 404:
        return HTTPException(status_code=404, detail="Playlist não encontrada.")
    if status in (401, 403):
        return HTTPException(status_code=401, detail="Sessão expirada, entre de novo.")
    return HTTPException(status_code=502, detail="Erro ao falar com o Spotify.")


@router.get("", response_model=list[PlaylistSummary])
async def list_playlists(request: Request):
    token = await get_valid_access_token(request)
    spotify = SpotifyClient(token)

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw_playlists = await spotify.get_all_playlists(client)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc

    return [
        PlaylistSummary(
            id=p["id"],
            name=p.get("name") or "Sem nome",
            description=p.get("description") or None,
            image=((p.get("images") or [{}])[0] or {}).get("url"),
            track_count=_track_count(p),
            owner=(p.get("owner") or {}).get("display_name"),
        )
        for p in raw_playlists
        if p is not None
    ]


def _track_count(playlist: dict) -> int:
    """Number of tracks in a playlist.

    The count moved from `tracks.total` to `items.total` in the 2026 API changes;
    `tracks` is deprecated but still sent, so fall back to it.
    """
    for key in ("items", "tracks"):
        total = (playlist.get(key) or {}).get("total")
        if total is not None:
            return total
    return 0


@router.get("/{playlist_id}/analysis", response_model=PlaylistAnalysis)
async def analyze_playlist(playlist_id: str, request: Request):
    token = await get_valid_access_token(request)
    try:
        return await build_playlist_analysis(token, playlist_id)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc
