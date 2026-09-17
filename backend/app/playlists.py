"""Routes for listing the user's playlists and analyzing one in detail."""
import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from . import analysis_store, profile_store
from .auth import get_valid_access_token
from .clustering import cluster_playlist
from .cache import playlist_analysis_cache, user_playlists_cache
from .genre_analysis import add_audio, build_playlist_analysis
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
    """Chave estável por conta, sem guardar o token em lugar nenhum.

    O id do Spotify vem na sessão desde o login e não muda nunca. Sem ele (uma
    sessão de antes dessa mudança), cai num hash do refresh token — o access
    token muda a cada renovação e jogaria o cache fora sem motivo.
    """
    user_id = (request.session.get("me") or {}).get("id")
    if user_id:
        return f"spotify:{user_id}"
    seed = request.session.get("refresh_token") or request.session.get("access_token") or ""
    return hashlib.sha256(seed.encode()).hexdigest()[:32]


# ── última listagem no banco ────────────────────────────────────────────────
#
# A listagem vive 5 minutos em memória, mas um reinício do backend a perdia e a
# próxima visita pedia tudo de novo ao Spotify. No banco ela serve a três casos:
# evita repaginar logo depois de um reinício, mantém as páginas funcionando
# enquanto o Spotify está bloqueado, e é a prova de que esta conta pode ver as
# análises guardadas de cada playlist (`analysis_for_user`).

LISTING_TTL = 60 * 5


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
        on_disk = await asyncio.to_thread(analysis_store.load_listing, cache_key)
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
            on_disk = await asyncio.to_thread(analysis_store.load_listing, cache_key)
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
    await asyncio.to_thread(analysis_store.save_listing, cache_key, summaries)
    return summaries


async def known_playlists(request: Request) -> list[PlaylistSummary]:
    """A última listagem conhecida desta conta, de qualquer idade.

    Diferente de `get_playlist_summaries`, não vai ao Spotify só porque a
    listagem passou de 5 minutos: ela serve para saber quais playlists a conta
    pode ver e em que versão estavam da última vez. O Spotify só é chamado se a
    conta nunca listou nada.
    """
    cache_key = _user_cache_key(request)
    cached = user_playlists_cache.get(cache_key)
    if cached is not None:
        return cached
    stored = await asyncio.to_thread(analysis_store.load_listing, cache_key)
    if stored:
        return stored[0]
    return await get_playlist_summaries(request)


def account_key(request: Request) -> str:
    """Chave da conta logada para o que é por pessoa (varredura, estatísticas)."""
    return _user_cache_key(request)


async def account_track_ids(request: Request) -> list[str]:
    """Ids das faixas que esta conta já analisou, de todas as playlists dela.

    O índice vetorial é um só para o app (uma faixa indexada serve a qualquer
    conta que a tenha), então tudo que consulta o índice em nome de uma pessoa —
    busca, faixas parecidas, painel do perfil — se limita a esta lista. Sem isso,
    a busca de uma conta devolveria faixas das playlists privadas de outra.

    Sai dos resumos do perfil no banco: nenhuma chamada externa.
    """
    listing = await known_playlists(request)

    def collect() -> list[str]:
        ids: set[str] = set()
        for playlist in listing:
            digest = profile_store.load(playlist.id)
            if digest:
                ids.update(t["id"] for t in digest.get("tracks", []) if t.get("id"))
        return sorted(ids)

    return await asyncio.to_thread(collect)


async def _remember_snapshot(request: Request, analysis: PlaylistAnalysis) -> None:
    """Leva para a listagem guardada a versão que acabou de ser lida.

    Sem isso, abrir uma playlist logo depois de mexer nela no Spotify leria a
    versão nova, mas a listagem (em cache) ainda apontaria a antiga — e cada
    visita seguinte refaria a análise até a listagem expirar."""
    cache_key = _user_cache_key(request)
    snapshot = analysis.playlist.snapshot_id
    listing = await known_playlists(request)
    if not snapshot or not any(p.id == analysis.playlist.id and p.snapshot_id != snapshot for p in listing):
        return
    updated = [
        p.model_copy(update={"snapshot_id": snapshot, "track_count": analysis.playlist.track_count})
        if p.id == analysis.playlist.id
        else p
        for p in listing
    ]
    if cache_key in user_playlists_cache:
        user_playlists_cache[cache_key] = updated
    stored = await asyncio.to_thread(analysis_store.load_listing, cache_key)
    await asyncio.to_thread(analysis_store.save_listing, cache_key, updated, stored[1] if stored else None)


async def analysis_for_user(
    request: Request, playlist_id: str, *, refresh: bool = False
) -> tuple[PlaylistAnalysis, bool]:
    """A análise da playlist para a conta logada, do jeito mais barato possível.

    Devolve (análise, lida_agora_do_spotify). Em ordem:

    1. **Guardada**, se a playlist está na listagem desta conta e a versão
       (`snapshot_id`) bate — zero chamadas externas.
    2. **Guardada sem áudio** (veio de uma varredura): completa só com o Deezer.
    3. **Do Spotify**, quando não há nada guardado, a versão mudou, ou `refresh`.

    A listagem da conta é a checagem de permissão: ela vem do Spotify e só tem
    playlists que esta conta pode ler. Uma playlist fora dela nunca é servida
    do banco nem do cache — vai ao Spotify, que responde 403 se não puder.
    """
    token = await get_valid_access_token(request)
    summary = next((p for p in await known_playlists(request) if p.id == playlist_id), None)

    if summary is None:
        return await build_playlist_analysis(token, playlist_id, trust_cache=False), True

    if not refresh:
        stored = await asyncio.to_thread(analysis_store.load, playlist_id, summary.snapshot_id)
        if stored is not None:
            if not stored.has_audio:
                return await add_audio(stored.analysis), False
            # No cache em memória, as ferramentas do chat e os grupos de clima
            # (que leem pelo id, depois desta checagem) também não vão ao Spotify.
            playlist_analysis_cache[playlist_id] = stored.analysis
            return stored.analysis, False

    analysis = await build_playlist_analysis(token, playlist_id, trust_cache=not refresh)
    await _remember_snapshot(request, analysis)
    return analysis, True


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
    """`refresh=true` relê a playlist no Spotify mesmo com análise guardada."""
    try:
        analysis, fetched = await analysis_for_user(request, playlist_id, refresh=refresh)
    except httpx.HTTPStatusError as exc:
        raise _spotify_error(exc) from exc

    # Análise guardada já foi indexada quando foi feita.
    if fetched:
        background.add_task(_index_analysis, analysis)
    return analysis


@router.get("/{playlist_id}/clusters", response_model=PlaylistClusters)
async def playlist_clusters(playlist_id: str, request: Request):
    """Agrupa as faixas da playlist por clima.

    Roda sobre a mesma análise da página (guardada ou em voo), então não custa
    nenhuma chamada externa além da que a própria análise faria.
    """
    try:
        analysis, _ = await analysis_for_user(request, playlist_id)
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
