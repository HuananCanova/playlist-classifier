"""Varre as playlists da conta e alimenta o índice vetorial.

Até aqui o índice só crescia como efeito colateral de abrir uma playlist, então
a busca só enxergava o que já tinha sido visitado — um resultado vazio quase
nunca queria dizer "não existe". Este módulo fecha essa lacuna varrendo a conta
inteira.

O custo é menor do que a intuição sugere: `build_playlist_analysis` gasta ~2
chamadas ao Spotify por playlist (uma para a playlist, uma a cada 100 faixas).
O volume está no Last.fm — uma chamada por faixa e por artista — que não é a API
que bloqueou esta conta e ainda cacheia por 24h, com os artistas repetidos entre
playlists saindo de graça a partir da segunda.

Ainda assim, a varredura é sequencial e não paralela entre playlists. Ela roda
em segundo plano, sem ninguém esperando; o que se ganharia em tempo não paga o
risco de disparar rajadas contra uma conta com histórico de bloqueio.

Só um trabalho roda por vez, e o progresso é observável — uma varredura que o
usuário não consegue ver nem parar seria a mesma opacidade que causou o problema
original.
"""
import asyncio
import contextlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from .genre_analysis import build_playlist_analysis
from .spotify_auth import SpotifyAuthError, access_token_from_refresh_token
from .spotify_client import SpotifyClient
from .vector_store import CHROMA_PATH, index_tracks

logger = logging.getLogger(__name__)

# Estado do que já foi indexado, ao lado do próprio índice: os dois nascem e
# morrem juntos, e apagar `.chroma` tem que zerar a cobertura também.
ESTADO = CHROMA_PATH / "indexed_playlists.json"

# Pausa entre playlists. Não é rate limit de verdade — é uma folga deliberada
# para a varredura não parecer uma rajada.
PAUSA_ENTRE_PLAYLISTS = 0.4

# Teto de espera quando o Spotify devolve 429, para um Retry-After absurdo não
# deixar o trabalho pendurado por horas.
MAX_BACKOFF = 60.0


@dataclass
class IndexProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    indexed_tracks: int = 0
    current: str | None = None
    errors: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    # Preenchido quando o Spotify pede para esperar; o frontend mostra isso em
    # vez de parecer travado.
    waiting_seconds: float | None = None


_progress = IndexProgress()
_task: asyncio.Task | None = None
_lock = asyncio.Lock()


# ── estado persistido ────────────────────────────────────────────────────────

def _carregar_estado() -> dict[str, str]:
    """Mapa playlist_id -> snapshot_id da última indexação."""
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _salvar_estado(estado: dict[str, str]) -> None:
    try:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("Não consegui gravar o estado do índice em %s", ESTADO)


async def _listar_playlists(token: str) -> list[dict]:
    spotify = SpotifyClient(token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        return [p for p in await spotify.get_all_playlists(client) if p]


def _pendentes(playlists: list[dict], estado: dict[str, str]) -> list[dict]:
    """Playlists nunca indexadas, ou que mudaram desde a última vez.

    O `snapshot_id` do Spotify muda a cada alteração de conteúdo, então ele
    responde exatamente a pergunta certa — e evita reindexar 40 playlists
    intactas toda vez que a varredura roda.
    """
    return [
        p
        for p in playlists
        if estado.get(p["id"]) != (p.get("snapshot_id") or "sem-snapshot")
    ]


# ── varredura ────────────────────────────────────────────────────────────────

async def _indexar_uma(token: str, playlist: dict) -> int:
    analysis = await build_playlist_analysis(token, playlist["id"])
    return await index_tracks(
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


async def _rodar(refresh_token: str) -> None:
    global _progress

    try:
        token = await access_token_from_refresh_token(refresh_token)
        playlists = await _listar_playlists(token)
    except (SpotifyAuthError, httpx.HTTPError) as exc:
        _progress.errors.append(f"Não consegui listar as playlists: {exc}")
        _progress.running = False
        _progress.finished_at = time.time()
        return

    estado = _carregar_estado()
    pendentes = _pendentes(playlists, estado)

    _progress.total = len(pendentes)
    _progress.done = 0

    for playlist in pendentes:
        _progress.current = playlist.get("name") or playlist["id"]

        try:
            # Um token por playlist: eles valem uma hora e uma varredura grande
            # pode passar disso. Pedir de novo é barato e evita o trabalho
            # morrer no meio por expiração.
            token = await access_token_from_refresh_token(refresh_token)
            n = await _indexar_uma(token, playlist)

            _progress.indexed_tracks += n
            estado[playlist["id"]] = playlist.get("snapshot_id") or "sem-snapshot"
            _salvar_estado(estado)

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                espera = min(float(exc.response.headers.get("Retry-After", 5)), MAX_BACKOFF)
                logger.warning("Spotify pediu %.0fs de espera; pausando a varredura", espera)
                _progress.waiting_seconds = espera
                await asyncio.sleep(espera)
                _progress.waiting_seconds = None
                # Sem incrementar `done`: a playlist não foi feita, e a próxima
                # varredura a pega de novo por não estar no estado.
                continue
            _progress.errors.append(f"{_progress.current}: HTTP {exc.response.status_code}")

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.exception("Falha ao indexar %s", playlist["id"])
            _progress.errors.append(f"{_progress.current}: {type(exc).__name__}")

        _progress.done += 1
        await asyncio.sleep(PAUSA_ENTRE_PLAYLISTS)

    _progress.current = None
    _progress.running = False
    _progress.finished_at = time.time()
    logger.info(
        "Varredura concluída: %d playlists, %d faixas, %d erros",
        _progress.done, _progress.indexed_tracks, len(_progress.errors),
    )


async def start(refresh_token: str) -> IndexProgress:
    """Dispara a varredura, se já não houver uma rodando."""
    global _task, _progress

    async with _lock:
        if _progress.running:
            return _progress

        _progress = IndexProgress(running=True, started_at=time.time())
        _task = asyncio.create_task(_rodar(refresh_token))

        def _limpar(t: asyncio.Task) -> None:
            _progress.running = False
            if _progress.finished_at is None:
                _progress.finished_at = time.time()
            with contextlib.suppress(asyncio.CancelledError):
                t.result()

        _task.add_done_callback(_limpar)
        return _progress


async def cancel() -> None:
    if _task is not None and not _task.done():
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task


def progress() -> IndexProgress:
    return _progress


async def coverage(access_token: str) -> dict:
    """Quantas playlists da conta já estão no índice.

    É o número que transforma "a busca não achou" em "a busca ainda não viu" —
    a confusão que motivou este módulo.
    """
    try:
        playlists = await _listar_playlists(access_token)
    except httpx.HTTPError:
        return {"total_playlists": None, "indexed_playlists": None, "pending_playlists": None}

    estado = _carregar_estado()
    pendentes = _pendentes(playlists, estado)
    return {
        "total_playlists": len(playlists),
        "indexed_playlists": len(playlists) - len(pendentes),
        "pending_playlists": len(pendentes),
    }


def progress_dict() -> dict:
    return asdict(_progress)
