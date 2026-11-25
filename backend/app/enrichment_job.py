"""Enriquecimento do acervo: tags separadas (Last.fm) e BPM (Deezer) por faixa.

O que está guardado das análises antigas não tem evidência por faixa — tags de
artista e de faixa separadas e com peso, nem o andamento —, e sem ela a
classificação de subgênero não consegue se explicar. Este job busca isso para as
faixas da biblioteca da conta e, no fim, reclassifica o que está em disco.

Regras:

- **Nunca sozinho.** Só roda quando o usuário pede, uma vez por conta.
- **Zero Spotify.** As faixas vêm dos resumos já guardados; só Last.fm e Deezer
  são consultados (cada um com o cache e o ritmo que o seu cliente já tem).
- **Só o que falta.** Last.fm só para o campo de tags ainda vazio; Deezer só
  para quem nunca foi consultado. Refazer depois de uma falha busca só ela.
- **Falha não vira dado.** Uma consulta que falhou fica `None` (e conta como
  erro): guardar `[]` esconderia a faixa por semanas. "Deezer respondeu que não
  tem" é diferente, e é registrado (`deezer_checked_at` com bpm/id vazios).
"""
import asyncio
import contextlib
import logging
import math
import time
from dataclasses import asdict, dataclass, field

import httpx

from . import deezer_client, evidence_store, lastfm_client, reclassify, taxonomy
from .evidence_store import TrackEvidence
from .genre_analysis import LASTFM_CONCURRENCY, gather_with_concurrency
from .taxonomy import Tag

logger = logging.getLogger(__name__)

# Faixas por rodada: entre uma e outra o job pode ser cancelado e o progresso anda.
LOTE = 48

# Estimativa de tempo: ~3 faixas/s no pior caso (Deezer, o mais lento, aceita
# ~50 requisições por 5s e cada faixa custa até duas) = 180 faixas por minuto.
TRACKS_PER_MINUTE = 180


@dataclass
class EnrichProgress:
    running: bool = False
    total: int = 0
    done: int = 0
    current: str | None = None
    errors: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None


@dataclass
class _Job:
    progress: EnrichProgress = field(default_factory=EnrichProgress)
    task: asyncio.Task | None = None
    # Faixas ainda sem evidência completa, vistas pela última vez por este job.
    pending: int = 0


# Um job por conta (chave de playlists.account_key).
_jobs: dict[str, _Job] = {}
_lock = asyncio.Lock()


# ── fila ─────────────────────────────────────────────────────────────────────

def _genres_with_bpm(cache: dict[str, bool], genres: list[str]) -> bool:
    for genre in genres:
        if genre not in cache:
            cache[genre] = any(info.bpm for info in taxonomy.subgenres_of(genre))
        if cache[genre]:
            return True
    return False


def pending_tracks(digests: dict[str, dict]) -> list[dict]:
    """Faixas únicas dos resumos que ainda não têm evidência completa.

    Quem tem gênero com faixa de BPM (psytrance) vem primeiro: é onde a
    evidência muda a resposta. Lê o banco; chame fora do event loop."""
    unicas: dict[str, dict] = {}
    for digest in digests.values():
        for t in (digest or {}).get("tracks", []):
            tid = t.get("id")
            if tid and tid not in unicas:
                unicas[tid] = {
                    "id": tid,
                    "name": t.get("name") or "",
                    "artists": list(t.get("artists") or []),
                    "album": t.get("album"),
                    "genres": list(t.get("genres") or []),
                }
    faltam = set(evidence_store.missing(list(unicas)))
    fila = [unicas[tid] for tid in unicas if tid in faltam]
    cache: dict[str, bool] = {}
    # sorted é estável: dentro de cada grupo vale a ordem dos resumos.
    return sorted(fila, key=lambda t: not _genres_with_bpm(cache, t["genres"]))


def estimate_minutes(pending: int) -> int:
    """Minutos até acabar: pendentes / TRACKS_PER_MINUTE, para cima, mínimo 1."""
    return max(1, math.ceil(pending / TRACKS_PER_MINUTE)) if pending > 0 else 0


# ── busca ────────────────────────────────────────────────────────────────────

def _merge_artist_tags(per_artist: list[list[Tag]]) -> list[Tag]:
    """Junta as tags de vários artistas creditados; a repetida fica com o maior peso."""
    best: dict[str, Tag] = {}
    for tags in per_artist:
        for tag in tags:
            key = tag.name.strip().lower()
            if key not in best or tag.weight > best[key].weight:
                best[key] = tag
    return sorted(best.values(), key=lambda t: -t.weight)


async def _lastfm(client: httpx.AsyncClient, track: dict, have: TrackEvidence | None, errors: list[str]) -> dict:
    """Os campos de tags que faltam para esta faixa. Campo que falhou fica fora."""
    out: dict = {}
    artists = track["artists"]
    label = track["name"] or track["id"]

    if have is None or have.artist_tags is None:
        try:
            answers = [await lastfm_client.get_artist_tags(client, a) for a in artists]
            if any(isinstance(a, lastfm_client.NoAnswer) for a in answers):
                raise RuntimeError("Last.fm não respondeu")
            out["artist_tags"] = _merge_artist_tags(answers)
        except Exception as exc:
            errors.append(f"{label}: tags do artista ({type(exc).__name__})")

    if have is None or have.track_tags is None:
        try:
            tags = await lastfm_client.get_track_tags(client, artists[0] if artists else "", track["name"])
            if isinstance(tags, lastfm_client.NoAnswer):
                raise RuntimeError("Last.fm não respondeu")
            out["track_tags"] = list(tags)
        except Exception as exc:
            errors.append(f"{label}: tags da faixa ({type(exc).__name__})")
    return out


def _deezer_fields(info: dict) -> dict | None:
    """O que gravar da resposta do Deezer, ou None se foi falha (não grava)."""
    if isinstance(info, deezer_client.NotFound):
        return {"deezer_checked_at": time.time()}
    if isinstance(info, deezer_client.Incomplete) or info.get("deezer_id") is None:
        return None
    return {"deezer_id": info["deezer_id"], "bpm": info.get("bpm"), "deezer_checked_at": time.time()}


async def _lote(client: httpx.AsyncClient, lote: list[dict], progress: EnrichProgress) -> None:
    have = await asyncio.to_thread(evidence_store.get_many, [t["id"] for t in lote])
    campos: dict[str, dict] = {t["id"]: {} for t in lote}

    async def tags(t: dict) -> None:
        campos[t["id"]].update(await _lastfm(client, t, have.get(t["id"]), progress.errors))

    sem_deezer = [
        t for t in lote
        if (have.get(t["id"]) is None or have[t["id"]].deezer_checked_at is None) and t["artists"] and t["name"]
    ]

    async def deezer() -> None:
        if not sem_deezer:
            return
        pares = [(t["artists"][0], t["name"]) for t in sem_deezer]
        try:
            respostas = await deezer_client.get_many(client, pares)
        except Exception as exc:
            progress.errors.append(f"Deezer ({type(exc).__name__})")
            return
        for t, info in zip(sem_deezer, respostas):
            achado = _deezer_fields(info)
            if achado is None:
                progress.errors.append(f"{t['name']}: Deezer não respondeu")
            else:
                campos[t["id"]].update(achado)

    await asyncio.gather(
        gather_with_concurrency(LASTFM_CONCURRENCY, *(tags(t) for t in lote)),
        deezer(),
    )

    for t in lote:
        if campos[t["id"]]:
            await asyncio.to_thread(evidence_store.put, TrackEvidence(track_id=t["id"], **campos[t["id"]]))


async def _rodar(job: _Job, digests: dict[str, dict], fila: list[dict]) -> None:
    progress = job.progress
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i in range(0, len(fila), LOTE):
            lote = fila[i : i + LOTE]
            progress.current = lote[0]["name"] or lote[0]["id"]
            await _lote(client, lote, progress)
            progress.done += len(lote)
            job.pending = len(fila) - progress.done

    # Com a evidência nova, refaz o que está em disco (sem rede). Só ao concluir:
    # um job cancelado deixa a evidência guardada e a próxima rodada reclassifica.
    contagem = await asyncio.to_thread(reclassify.account, list(digests))
    logger.info(
        "Enriquecimento concluído: %d/%d faixas, %d erros, reclassificado %s",
        progress.done, progress.total, len(progress.errors), contagem,
    )


def _finalizar(job: _Job, task: asyncio.Task) -> None:
    progress = job.progress
    progress.current = None
    progress.running = False
    progress.finished_at = time.time()
    if not task.cancelled() and task.exception() is not None:
        logger.error("Enriquecimento falhou", exc_info=task.exception())
        progress.errors.append(f"Falha inesperada: {type(task.exception()).__name__}")


async def start(account: str, digests: dict[str, dict]) -> EnrichProgress:
    """Dispara o enriquecimento desta conta, se já não houver um rodando."""
    async with _lock:
        atual = _jobs.get(account)
        if atual is not None and atual.progress.running:
            return atual.progress

        fila = await asyncio.to_thread(pending_tracks, digests)
        if not fila:
            job = _Job(EnrichProgress(finished_at=time.time()))
            _jobs[account] = job
            return job.progress

        job = _Job(EnrichProgress(running=True, total=len(fila), started_at=time.time()), pending=len(fila))
        job.task = asyncio.create_task(_rodar(job, digests, fila))
        job.task.add_done_callback(lambda t: _finalizar(job, t))
        _jobs[account] = job
        return job.progress


async def cancel(account: str) -> None:
    job = _jobs.get(account)
    if job is None or job.task is None or job.task.done():
        return
    job.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await job.task


async def wait(account: str) -> None:
    """Espera o job desta conta terminar (testes)."""
    job = _jobs.get(account)
    if job is not None and job.task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await job.task


def progress_dict(account: str, pending: int | None = None) -> dict:
    """O progresso mais `pending` e `estimated_minutes`.

    `pending` vem de quem chama quando sabe (a rota recalcula contra o banco);
    senão vale o que o último job viu."""
    job = _jobs.get(account)
    progress = job.progress if job else EnrichProgress()
    if pending is None:
        pending = job.pending if job else 0
    return {**asdict(progress), "pending": pending, "estimated_minutes": estimate_minutes(pending)}
