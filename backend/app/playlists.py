"""Routes for listing the user's playlists and analyzing one in detail."""
import hashlib
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from .auth import get_valid_access_token
from .cache import playlist_analysis_cache, user_playlists_cache
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


def _user_cache_key(request: Request) -> str:
    """Chave estável por usuário, sem guardar o token em lugar nenhum.

    Usa o refresh token porque o access token muda a cada renovação e jogaria
    o cache fora sem motivo.
    """
    seed = request.session.get("refresh_token") or request.session.get("access_token") or ""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


@router.get("", response_model=list[PlaylistSummary])
async def list_playlists(request: Request, refresh: bool = False):
    """`refresh=true` ignora o cache — é a saída para quem acabou de mexer nas
    playlists no Spotify e não quer esperar o TTL expirar."""
    token = await get_valid_access_token(request)
    spotify = SpotifyClient(token)

    # A lista muda pouco e a página é recarregada muito (o StrictMode do React
    # sozinho já dobra as chamadas em dev). Sem este cache, cada visita
    # repaginava tudo — foi o que estourou o rate limit do Spotify.
    cache_key = _user_cache_key(request)
    if not refresh:
        cached = user_playlists_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw_playlists = await spotify.get_all_playlists(client)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc

    summaries = [
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
    user_playlists_cache[cache_key] = summaries
    return summaries


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
async def analyze_playlist(playlist_id: str, request: Request, refresh: bool = False):
    token = await get_valid_access_token(request)

    # Abrir uma playlist custa 1 chamada de metadados + 1 por página de 100
    # faixas, e o StrictMode do React dispara o efeito duas vezes em dev — ou
    # seja, reabrir a mesma playlist saía caro no orçamento do Spotify.
    # A chave inclui o usuário: sem isso, uma análise de playlist privada já
    # em cache seria devolvida a outra conta sem passar pela permissão do
    # Spotify. Este app é de um usuário só, mas o cache não deveria ser o
    # lugar onde essa garantia se perde.
    cache_key = f"{_user_cache_key(request)}:{playlist_id}"
    if not refresh:
        cached = playlist_analysis_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        analysis = await build_playlist_analysis(token, playlist_id)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc

    playlist_analysis_cache[cache_key] = analysis
    return analysis
