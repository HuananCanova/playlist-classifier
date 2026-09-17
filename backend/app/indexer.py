"""A varredura da conta: a única que lê playlists do Spotify em lote.

Ela alimenta duas coisas de uma vez — o índice vetorial da busca e os resumos
em disco do perfil (que `build_playlist_analysis` grava sozinho). Já existiram
duas varreduras separadas, uma por recurso, e cada uma relia a conta inteira;
foi o volume somado que levou o Spotify a suspender o app por 18 horas.

Por isso as regras aqui são de ritmo, não de velocidade:

- **Nunca sozinha.** Só roda quando o usuário pede (botão na busca ou no
  perfil). `AUTO_INDEX=true` volta a disparar ao abrir o app, se você quiser.
- **Só o que mudou.** Uma playlist entra na fila se não está no índice, se não
  tem resumo, ou se o `snapshot_id` mudou desde a última vez.
- **Uma por vez, com pausa**, e no máximo `MAX_PLAYLISTS_POR_HORA`. Cada
  playlist custa ~1 chamada + 1 a cada 100 faixas.
- **Sem Deezer.** O índice só precisa de tags; BPM e prévia ficam para quando a
  playlist é aberta.
- **Para no primeiro bloqueio longo**, e o bloqueio fica gravado em disco pelo
  `spotify_client` — nenhuma parte do app volta a chamar o Spotify até lá.

O progresso é observável e a varredura pode ser parada; o que já foi feito fica.

**Por conta, com uma fila só para o Spotify.** Cada conta tem a própria
varredura e o próprio progresso — uma pessoa não vê o nome das playlists da
outra, nem para a varredura dela. Mas o limite do Spotify é do app inteiro, não
de cada conta, então a leitura no Spotify passa por uma vez só (`_vez`) e o teto
por hora é contado para todas as contas juntas. Duas contas varrendo ao mesmo
tempo andam alternadas, no mesmo ritmo de uma.
"""
import asyncio
import contextlib
import json
import logging
import math
import time
import threading
from collections import deque
from dataclasses import asdict, dataclass, field

import httpx

from . import analysis_store, profile_store
from .genre_analysis import build_playlist_analysis
from .spotify_auth import SpotifyAuthError, access_token_from_refresh_token
from .spotify_client import GLOBAL_BLOCK_SECONDS, global_block_remaining
from .vector_store import CHROMA_PATH, index_tracks

logger = logging.getLogger(__name__)

# Estado do que já foi indexado, ao lado do próprio índice: os dois nascem e
# morrem juntos, e apagar `.chroma` tem que zerar a cobertura também.
ESTADO = CHROMA_PATH / "indexed_playlists.json"

# Pausa entre playlists. Não é o rate limit do Spotify (que ele não publica) —
# é uma folga deliberada para a varredura nunca parecer uma rajada.
PAUSA_ENTRE_PLAYLISTS = 2.0

# Teto por hora. A 60 playlists/hora uma conta de 113 leva ~2 horas na primeira
# vez; depois disso só entram as que mudaram, e o teto quase nunca é atingido.
MAX_PLAYLISTS_POR_HORA = 60

# Uma playlist cuja espera curta se repete mais que isso desiste nesta rodada.
MAX_TENTATIVAS = 3

# Access tokens valem uma hora; renova com folga.
TOKEN_TTL = 50 * 60


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
    # Preenchido durante uma espera (curta do Spotify, ou do teto por hora); o
    # frontend mostra isso em vez de parecer travado.
    waiting_seconds: float | None = None
    # Quanto falta do bloqueio geral do Spotify, quando ele parou a varredura.
    blocked_seconds: float | None = None
    # Esperando a vez de ler o Spotify enquanto a varredura de outra conta lê.
    waiting_turn: bool = False


@dataclass
class _Varredura:
    progress: IndexProgress = field(default_factory=IndexProgress)
    task: asyncio.Task | None = None


# Uma varredura por conta (chave de playlists._user_cache_key).
_varreduras: dict[str, _Varredura] = {}
_lock = asyncio.Lock()

# Uma leitura no Spotify por vez no app inteiro, e o teto por hora somado.
_vez = asyncio.Lock()
_feitas_na_hora: deque[float] = deque()

# O arquivo de estado é compartilhado por todas as varreduras.
_estado_lock = threading.Lock()


# ── estado persistido ────────────────────────────────────────────────────────

def _carregar_estado() -> dict[str, str]:
    """Mapa playlist_id -> snapshot_id da última indexação."""
    try:
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _marcar_indexada(playlist: dict) -> None:
    """Grava uma playlist como indexada, relendo o arquivo antes.

    Com duas varreduras (de contas diferentes) rodando, cada uma gravar o mapa
    que leu no início apagaria o que a outra acabou de marcar."""
    with _estado_lock:
        estado = _carregar_estado()
        estado[playlist["id"]] = _snapshot(playlist)
        _salvar_estado(estado)


def _salvar_estado(estado: dict[str, str]) -> None:
    try:
        ESTADO.parent.mkdir(parents=True, exist_ok=True)
        ESTADO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("Não consegui gravar o estado do índice em %s", ESTADO)


def _snapshot(playlist: dict) -> str:
    return playlist.get("snapshot_id") or "sem-snapshot"


def _pendentes(playlists: list[dict], estado: dict[str, str]) -> list[dict]:
    """Playlists nunca indexadas, ou que mudaram desde a última vez.

    O `snapshot_id` do Spotify muda a cada alteração de conteúdo, então ele
    responde exatamente a pergunta certa — e evita reindexar 40 playlists
    intactas toda vez que a varredura roda.
    """
    return [p for p in playlists if estado.get(p["id"]) != _snapshot(p)]


def pendentes_da_conta(playlists: list[dict], estado: dict[str, str] | None = None) -> list[dict]:
    """O que a varredura faria agora: falta no índice OU falta resumo do perfil.

    Playlists vazias ficam de fora (não há o que ler), e as menores vêm antes —
    a cobertura sobe mais rápido e as gigantes ficam para o fim.
    Lê disco; chame fora do event loop.
    """
    estado = _carregar_estado() if estado is None else estado
    sem_indice = {p["id"] for p in _pendentes(playlists, estado)}
    fila = [
        p
        for p in playlists
        if p.get("track_count", 1)
        and (
            p["id"] in sem_indice
            or not profile_store.is_fresh(profile_store.load(p["id"]), p.get("snapshot_id"))
        )
    ]
    return sorted(fila, key=lambda p: p.get("track_count", 0))


def estimar_chamadas(playlists: list[dict]) -> int:
    """Chamadas ao Spotify para ler estas playlists: 1 de metadados + 1 por página de 100."""
    return sum(1 + max(1, math.ceil((p.get("track_count") or 0) / 100)) for p in playlists)


# ── varredura ────────────────────────────────────────────────────────────────

async def _analise_guardada(playlist: dict):
    """A análise já guardada desta versão da playlist, se houver.

    A fila também recebe playlists que só perderam o índice (ex.: `.chroma`
    apagado) ou o resumo do perfil. Para essas, reler o Spotify é desperdício:
    a análise da mesma versão está no banco."""
    stored = await asyncio.to_thread(analysis_store.load, playlist["id"], playlist.get("snapshot_id"))
    if stored is None or not playlist.get("snapshot_id"):
        return None
    await asyncio.to_thread(profile_store.save, stored.analysis, has_audio=stored.has_audio)
    return stored.analysis


async def _indexar_uma(token: str | None, playlist: dict, analysis=None) -> int:
    if analysis is None:
        analysis = await build_playlist_analysis(token, playlist["id"], include_audio=False)
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


def _retry_after(exc: httpx.HTTPStatusError) -> float:
    try:
        return float(exc.response.headers.get("Retry-After", 5))
    except ValueError:
        return 5.0


async def _esperar(progress: IndexProgress, segundos: float) -> None:
    progress.waiting_seconds = segundos
    try:
        await asyncio.sleep(segundos)
    finally:
        progress.waiting_seconds = None


async def _respeitar_teto(progress: IndexProgress) -> None:
    """Teto por hora, somado entre as contas: espera a janela abrir."""
    agora = time.time()
    while _feitas_na_hora and agora - _feitas_na_hora[0] > 3600:
        _feitas_na_hora.popleft()
    if len(_feitas_na_hora) >= MAX_PLAYLISTS_POR_HORA:
        await _esperar(progress, 3600 - (agora - _feitas_na_hora[0]) + 1)


async def _rodar(progress: IndexProgress, refresh_token: str, fila: list[dict]) -> None:
    token: str | None = None
    token_em = 0.0

    for playlist in fila:
        bloqueio = global_block_remaining()
        if bloqueio:
            progress.blocked_seconds = bloqueio
            break

        progress.current = playlist.get("name") or playlist["id"]

        guardada = await _analise_guardada(playlist)
        if guardada is not None:
            # Sem Spotify: não espera a vez, não conta no teto nem pede pausa.
            try:
                progress.indexed_tracks += await _indexar_uma(None, playlist, guardada)
                await asyncio.to_thread(_marcar_indexada, playlist)
            except Exception as exc:
                logger.exception("Falha ao indexar %s", playlist["id"])
                progress.errors.append(f"{progress.current}: {type(exc).__name__}")
            progress.done += 1
            continue

        progress.waiting_turn = _vez.locked()
        async with _vez:
            progress.waiting_turn = False
            await _respeitar_teto(progress)

            for tentativa in range(MAX_TENTATIVAS):
                # Outra conta pode ter levado um bloqueio enquanto esta esperava a vez.
                bloqueio = global_block_remaining()
                if bloqueio:
                    progress.blocked_seconds = bloqueio
                    break
                try:
                    if token is None or time.time() - token_em > TOKEN_TTL:
                        token = await access_token_from_refresh_token(refresh_token)
                        token_em = time.time()

                    progress.indexed_tracks += await _indexar_uma(token, playlist)
                    await asyncio.to_thread(_marcar_indexada, playlist)
                    break

                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 429:
                        progress.errors.append(f"{progress.current}: HTTP {exc.response.status_code}")
                        break
                    espera = _retry_after(exc)
                    if espera > GLOBAL_BLOCK_SECONDS or tentativa == MAX_TENTATIVAS - 1:
                        # O spotify_client já gravou o bloqueio; aqui só se para.
                        progress.blocked_seconds = global_block_remaining() or espera
                        logger.warning("Varredura parada: Spotify pediu %.0fs de espera", espera)
                        break
                    logger.info("Spotify pediu %.0fs; repetindo %s", espera, progress.current)
                    await _esperar(progress, espera)

                except SpotifyAuthError as exc:
                    progress.errors.append(str(exc))
                    progress.blocked_seconds = None
                    return

                except asyncio.CancelledError:
                    raise

                except Exception as exc:
                    logger.exception("Falha ao indexar %s", playlist["id"])
                    progress.errors.append(f"{progress.current}: {type(exc).__name__}")
                    break

            if progress.blocked_seconds:
                break

            progress.done += 1
            _feitas_na_hora.append(time.time())
            # A pausa fica dentro da vez: é ela que espaça as leituras do app todo.
            await asyncio.sleep(PAUSA_ENTRE_PLAYLISTS)

    logger.info(
        "Varredura concluída: %d/%d playlists, %d faixas, %d erros",
        progress.done, progress.total, progress.indexed_tracks, len(progress.errors),
    )


def _finalizar(progress: IndexProgress, task: asyncio.Task) -> None:
    progress.current = None
    progress.waiting_seconds = None
    progress.waiting_turn = False
    progress.running = False
    progress.finished_at = time.time()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.result()


async def start(account: str, refresh_token: str, playlists: list[dict]) -> IndexProgress:
    """Dispara a varredura do que falta nesta conta, se já não houver uma rodando.

    `playlists` vem da listagem em cache de quem chama: a varredura não lista a
    conta por conta própria, então pedir para começar não custa chamada nenhuma.
    """
    async with _lock:
        atual = _varreduras.get(account)
        if atual is not None and atual.progress.running:
            return atual.progress

        anterior = atual.progress.finished_at if atual else None
        bloqueio = global_block_remaining()
        if bloqueio:
            progress = IndexProgress(blocked_seconds=bloqueio, finished_at=anterior)
            _varreduras[account] = _Varredura(progress)
            return progress

        fila = await asyncio.to_thread(pendentes_da_conta, playlists)
        if not fila:
            progress = IndexProgress(finished_at=time.time())
            _varreduras[account] = _Varredura(progress)
            return progress

        progress = IndexProgress(running=True, total=len(fila), started_at=time.time())
        task = asyncio.create_task(_rodar(progress, refresh_token, fila))
        task.add_done_callback(lambda t: _finalizar(progress, t))
        _varreduras[account] = _Varredura(progress, task)
        return progress


async def cancel(account: str) -> None:
    varredura = _varreduras.get(account)
    if varredura is None or varredura.task is None or varredura.task.done():
        return
    varredura.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await varredura.task


async def wait(account: str) -> None:
    """Espera a varredura desta conta terminar (testes)."""
    varredura = _varreduras.get(account)
    if varredura is not None and varredura.task is not None:
        with contextlib.suppress(asyncio.CancelledError):
            await varredura.task


def progress(account: str) -> IndexProgress:
    varredura = _varreduras.get(account)
    return varredura.progress if varredura else IndexProgress()


def coverage(playlists: list[dict]) -> dict:
    """Quanto da conta já está pronto — sem chamar o Spotify.

    É o número que transforma "a busca não achou" em "a busca ainda não viu".
    Lê disco; chame fora do event loop.
    """
    com_faixas = [p for p in playlists if p.get("track_count", 1)]
    fila = pendentes_da_conta(com_faixas)
    return {
        "total_playlists": len(com_faixas),
        "indexed_playlists": len(com_faixas) - len(fila),
        "pending_playlists": len(fila),
        "estimated_calls": estimar_chamadas(fila),
    }


def progress_dict(account: str) -> dict:
    atual = progress(account)
    data = asdict(atual)
    if not atual.running:
        # Tempo restante de verdade, inclusive depois de um reinício.
        data["blocked_seconds"] = global_block_remaining()
    return data
