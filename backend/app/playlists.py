"""Routes for listing the user's playlists and analyzing one in detail."""
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from .auth import get_valid_access_token
from .clustering import cluster_playlist
from .cache import playlist_analysis_cache, user_playlists_cache
from .genre_analysis import build_playlist_analysis
from .models import PlaylistAnalysis, PlaylistClusters, PlaylistSummary
from . import spotify_client
from .spotify_client import SpotifyClient
from .vector_store import index_tracks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/playlists", tags=["playlists"])


def wait_text(seconds: float) -> str:
    """"~18 h (até 10:57)" / "~40 s" — para mensagens que um humano vai ler."""
    if seconds < 90:
        return f"~{int(seconds)} s"
    until = (datetime.now() + timedelta(seconds=seconds)).strftime("%d/%m %H:%M" if seconds > 12 * 3600 else "%H:%M")
    span = f"~{round(seconds / 3600)} h" if seconds >= 5400 else f"~{round(seconds / 60)} min"
    return f"{span} (até {until})"


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
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = 0.0
        detail = (
            f"O Spotify suspendeu o acesso deste app por {wait_text(seconds)}. "
            "O app não chama o Spotify até lá, porque insistir aumenta a espera."
            if seconds > spotify_client.GLOBAL_BLOCK_SECONDS
            else "O Spotify limitou as requisições temporariamente. Tente de novo em instantes."
        )
        return HTTPException(
            status_code=429,
            detail=detail,
            # Repassado para o front conseguir dizer quantos segundos faltam.
            headers={"Retry-After": retry_after} if retry_after else None,
        )
    if status == 404:
        return HTTPException(status_code=404, detail="Playlist não encontrada.")
    if status == 403:
        # Não é sessão expirada: o Spotify só libera as faixas de playlists do
        # próprio usuário ou colaborativas. Tratar como 401 derrubava o login.
        return HTTPException(
            status_code=403,
            detail="O Spotify só permite abrir playlists criadas por você ou colaborativas.",
        )
    if status == 401:
        return HTTPException(status_code=401, detail="Sessão expirada, entre de novo.")
    return HTTPException(status_code=502, detail="Erro ao falar com o Spotify.")


def _user_cache_key(request: Request) -> str:
    """Chave estável por usuário, sem guardar o token em lugar nenhum.

    Usa o refresh token porque o access token muda a cada renovação e jogaria
    o cache fora sem motivo.
    """
    seed = request.session.get("refresh_token") or request.session.get("access_token") or ""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


# ── última listagem em disco ────────────────────────────────────────────────
#
# A listagem vive 5 minutos em memória, mas um reinício do backend a perdia e a
# próxima visita pedia tudo de novo ao Spotify. Em disco ela serve a dois casos:
# evita repaginar logo depois de um reinício e mantém as páginas funcionando
# enquanto o Spotify está bloqueado — com a última lista conhecida.

LISTING_TTL = 60 * 5


def _listing_file(cache_key: str):
    return spotify_client.STATE_PATH / f"playlists-{cache_key}.json"


def _read_listing(cache_key: str) -> tuple[list[PlaylistSummary], float] | None:
    try:
        data = json.loads(_listing_file(cache_key).read_text(encoding="utf-8"))
        return [PlaylistSummary(**p) for p in data["playlists"]], float(data["saved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_listing(cache_key: str, summaries: list[PlaylistSummary]) -> None:
    path = _listing_file(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps({"saved_at": time.time(), "playlists": [p.model_dump() for p in summaries]}, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        logger.warning("Não consegui gravar a listagem em %s", path)


@router.get("", response_model=list[PlaylistSummary])
async def list_playlists(request: Request, refresh: bool = False):
    """`refresh=true` ignora o cache — é a saída para quem acabou de mexer nas
    playlists no Spotify e não quer esperar o TTL expirar."""
    return await get_playlist_summaries(request, refresh=refresh)


async def get_playlist_summaries(request: Request, refresh: bool = False) -> list[PlaylistSummary]:
    """A listagem com cache por usuário — compartilhada com o perfil."""
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
        on_disk = _read_listing(cache_key)
        if on_disk and time.time() - on_disk[1] < LISTING_TTL:
            user_playlists_cache[cache_key] = on_disk[0]
            return on_disk[0]

    # O id já está na sessão desde o login; sem ele a listagem gastaria um /me.
    user_id = (request.session.get("me") or {}).get("id")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            raw_playlists = await spotify.get_all_playlists(client, user_id=user_id)
    except httpx.HTTPStatusError as exc:
        # Com o Spotify bloqueado, a última lista conhecida é melhor que um erro.
        if exc.response.status_code == 429:
            on_disk = _read_listing(cache_key)
            if on_disk:
                logger.info("Spotify bloqueado; servindo a listagem de %s", datetime.fromtimestamp(on_disk[1]))
                return on_disk[0]
        raise _spotify_error(exc) from exc

    summaries = [
        PlaylistSummary(
            id=p["id"],
            name=p.get("name") or "Sem nome",
            description=p.get("description") or None,
            image=((p.get("images") or [{}])[0] or {}).get("url"),
            track_count=_track_count(p),
            owner=(p.get("owner") or {}).get("display_name"),
            snapshot_id=p.get("snapshot_id"),
        )
        for p in raw_playlists
        if p is not None
    ]
    user_playlists_cache[cache_key] = summaries
    _write_listing(cache_key, summaries)
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
async def analyze_playlist(
    playlist_id: str, request: Request, background: BackgroundTasks, refresh: bool = False
):
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
    background.add_task(_index_analysis, analysis)
    return analysis


@router.get("/{playlist_id}/clusters", response_model=PlaylistClusters)
async def playlist_clusters(playlist_id: str, request: Request):
    """Agrupa as faixas da playlist por clima.

    Roda sobre a análise já cacheada, então não custa nenhuma chamada externa
    além da que a própria análise faria.
    """
    token = await get_valid_access_token(request)
    try:
        analysis = await build_playlist_analysis(token, playlist_id)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc

    resultado = await cluster_playlist(analysis)
    return PlaylistClusters(
        clusters=[
            {
                "id": c.id,
                "label": c.label,
                "size": c.size,
                "top_tags": c.top_tags,
                "track_ids": c.track_ids,
                "sample_tracks": c.sample_tracks,
            }
            for c in resultado.clusters
        ],
        k=resultado.k,
        silhouette=resultado.silhouette,
        points=[
            {"track_id": tid, "x": x, "y": y, "cluster": cid}
            for tid, x, y, cid in resultado.points
        ],
        note=resultado.note,
    )


async def _index_analysis(analysis: PlaylistAnalysis) -> None:
    """Alimenta o índice vetorial com as faixas de uma análise já pronta."""
    try:
        await index_tracks(
            [
                {
                    "track_id": t.track_id,
                    "nome": t.name,
                    "artistas": t.artists,
                    "album": t.album,
                    "tags": t.subgenre_tags,
                }
                for t in analysis.tracks
            ]
        )
    except Exception:
        # Indexar é enriquecimento, não o produto: se o índice falhar, a análise
        # que o usuário pediu já foi entregue e não deve virar um erro.
        logger.exception("Falha ao indexar a playlist %s", analysis.playlist.id)
