"""Thin async wrapper around the bits of the Spotify Web API this app needs.

Toda chamada ao Spotify do app passa por aqui — inclusive o `/me` do login e o
detalhe de faixa —, porque é aqui que mora a proteção contra bloqueio. Uma
chamada que saísse por fora dela era justamente o tipo de requisição que
continuava batendo numa conta bloqueada e esticava o bloqueio.
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.spotify.com/v1"

# O Spotify limita por endpoint numa janela deslizante, e abrir a lista de
# playlists várias vezes seguidas basta para estourar. Quase sempre a janela é
# de poucos segundos, então uma espera curta resolve sem o usuário ver erro.
MAX_RETRIES = 2
# Acima disso não vale segurar a requisição: melhor devolver 429 e deixar a
# interface dizer quanto falta do que deixar a página pendurada.
MAX_RETRY_WAIT_SECONDS = 8.0

# Esperas acima disso não são a janela curta de um endpoint: são o Spotify
# suspendendo o app (já vieram esperas de 18 horas). Nesse caso o bloqueio vale
# para todas as rotas e é gravado em disco, para um reinício do backend não
# voltar a chamar uma API bloqueada.
GLOBAL_BLOCK_SECONDS = 60.0

# Estado que precisa sobreviver a reinícios (bloqueio, última listagem).
STATE_PATH = Path(__file__).resolve().parent.parent / ".state"

# Até quando cada endpoint está bloqueado, por rota ("/v1/playlists/{id}/items").
_throttled_until: dict[str, float] = {}

# Bloqueio do app inteiro; `None` = ainda não lido do disco neste processo.
_global_until: float | None = None

# Quantas chamadas realmente saíram para o Spotify desde que o processo subiu.
# Serve para o health check dizer se o "não há bloqueio" é uma informação ou
# apenas ausência de informação.
_calls_since_boot = 0

# Ids viram {id}: o limite é por rota, e com o id na chave cada playlist nova
# parecia um endpoint livre — abrir outra playlist chamava o Spotify de novo.
_ID_SEGMENT = re.compile(r"/(playlists|tracks|artists|albums|users|shows|episodes)/[^/]+")


def _throttle_key(url: str) -> str:
    path = urllib.parse.urlparse(str(url)).path
    return _ID_SEGMENT.sub(lambda m: f"/{m.group(1)}/{{id}}", path)


def _block_file() -> Path:
    return STATE_PATH / "spotify_block.json"


def global_block_remaining() -> float | None:
    """Segundos até o fim do bloqueio geral, ou `None` se não há bloqueio."""
    global _global_until
    if _global_until is None:
        try:
            _global_until = float(json.loads(_block_file().read_text(encoding="utf-8"))["until"])
        except (OSError, ValueError, KeyError, TypeError):
            _global_until = 0.0
    remaining = _global_until - time.time()
    return remaining if remaining > 0 else None


def _set_global_block(seconds: float) -> None:
    global _global_until
    until = time.time() + seconds
    if until <= (_global_until or 0):
        return
    _global_until = until
    try:
        STATE_PATH.mkdir(parents=True, exist_ok=True)
        tmp = _block_file().with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"until": until}), encoding="utf-8")
        os.replace(tmp, _block_file())
    except OSError:
        logger.warning("Não consegui gravar o bloqueio do Spotify em %s", _block_file())


def _remember_throttle(url: str, resp: httpx.Response) -> None:
    try:
        wait = float(resp.headers.get("Retry-After", 1))
    except ValueError:
        wait = 1.0
    if wait > GLOBAL_BLOCK_SECONDS:
        _set_global_block(wait)
        logger.warning("Spotify suspendeu o app por %.0fs (%.1f h) — nenhuma chamada até lá", wait, wait / 3600)
    else:
        _throttled_until[_throttle_key(url)] = time.time() + wait
        logger.warning("Spotify limitou %s por %.0fs", _throttle_key(url), wait)


def _raise_if_throttled(url: str) -> None:
    """Falha na hora, sem chamar o Spotify, enquanto houver bloqueio."""
    remaining = global_block_remaining() or (_throttled_until.get(_throttle_key(url), 0) - time.time())
    if remaining <= 0:
        return

    request = httpx.Request("GET", url)
    response = httpx.Response(
        429, headers={"Retry-After": str(int(remaining) + 1)}, request=request
    )
    raise httpx.HTTPStatusError(
        f"Bloqueado localmente por mais {int(remaining)}s", request=request, response=response
    )


def throttle_state() -> dict:
    """Diagnóstico do rate limit para o /api/health.

    `checked` existe porque um dicionário de bloqueios vazio é ambíguo: pode
    significar "não está bloqueado" ou "ainda não falamos com o Spotify desde
    que o processo subiu". Sem distinguir os dois, o health check não responde
    a pergunta que importa — já passou?
    """
    now = time.time()
    blocked = {
        path: int(until - now)
        for path, until in _throttled_until.items()
        if until > now
    }
    global_remaining = global_block_remaining()
    return {
        "checked": _calls_since_boot > 0 or global_remaining is not None,
        "calls_since_boot": _calls_since_boot,
        "global_block_seconds": int(global_remaining) if global_remaining else None,
        "blocked": blocked,
        "summary": (
            f"app suspenso pelo Spotify por mais {global_remaining / 3600:.1f} h"
            if global_remaining
            else "sem contato com o Spotify desde o restart — recarregue a página para descobrir"
            if _calls_since_boot == 0
            else f"bloqueado: {blocked}" if blocked
            else "liberado"
        ),
    }


class SpotifyClient:
    def __init__(self, access_token: str):
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """GET com repetição em 429, respeitando o Retry-After do Spotify."""
        # Se já sabemos que este endpoint está bloqueado, nem tenta: continuar
        # batendo numa API que respondeu 429 é justamente o que faz o Spotify
        # esticar o bloqueio de segundos para horas.
        _raise_if_throttled(url)

        global _calls_since_boot

        for attempt in range(MAX_RETRIES + 1):
            resp = await client.get(url, headers=self._headers, **kwargs)
            _calls_since_boot += 1

            if resp.status_code == 429:
                _remember_throttle(url, resp)

            if resp.status_code != 429 or attempt == MAX_RETRIES:
                resp.raise_for_status()
                return resp

            # Retry-After vem em segundos; sem o cabeçalho, 1s é o palpite seguro.
            try:
                wait = float(resp.headers.get("Retry-After", 1))
            except ValueError:
                wait = 1.0

            if wait > MAX_RETRY_WAIT_SECONDS:
                logger.warning("Spotify 429 em %s, Retry-After=%ss — devolvendo ao cliente", url, wait)
                resp.raise_for_status()

            logger.info("Spotify 429 em %s — repetindo em %.1fs", url, wait)
            await asyncio.sleep(wait)

        return resp  # inalcançável: o laço sempre retorna ou levanta

    async def get_me(self, client: httpx.AsyncClient) -> dict:
        resp = await self._get(client, f"{BASE_URL}/me")
        return resp.json()

    async def get_current_user_id(self, client: httpx.AsyncClient) -> str | None:
        return (await self.get_me(client)).get("id")

    async def get_track(self, client: httpx.AsyncClient, track_id: str) -> dict:
        resp = await self._get(client, f"{BASE_URL}/tracks/{track_id}")
        return resp.json()

    async def get_all_playlists(self, client: httpx.AsyncClient, user_id: str | None = None) -> list[dict]:
        """Playlists da conta cujas faixas o Spotify deixa ler.

        `/me/playlists` também devolve as playlists que o usuário apenas segue,
        mas desde fevereiro de 2026 `/playlists/{id}/items` responde 403 para
        qualquer playlist que não seja dele nem colaborativa. Listá-las só
        levaria o usuário a um erro ao abrir, então ficam de fora aqui.

        `user_id` evita uma chamada a `/me` quando quem pede já sabe quem é.
        """
        if user_id is None:
            user_id = await self.get_current_user_id(client)
        playlists: list[dict] = []
        url = f"{BASE_URL}/me/playlists?limit=50"
        while url:
            resp = await self._get(client, url)
            data = resp.json()
            playlists.extend(
                p for p in data.get("items", []) if is_accessible_playlist(p, user_id)
            )
            url = data.get("next")
        return playlists

    async def get_playlist(self, client: httpx.AsyncClient, playlist_id: str) -> dict:
        resp = await self._get(client, f"{BASE_URL}/playlists/{playlist_id}")
        return resp.json()

    async def get_all_playlist_tracks(self, client: httpx.AsyncClient, playlist_id: str) -> list[dict]:
        """Returns the playlist's track objects.

        Uses /playlists/{id}/items — the old /tracks endpoint was removed in the
        February 2026 API migration, and each entry's `track` field is now `item`.
        """
        tracks: list[dict] = []
        url = (
            # Sem preview_url: o Spotify parou de preencher esse campo para apps
            # criados depois de 27/11/2024, e ele voltava None em toda faixa.
            # As prévias agora vêm do Deezer (deezer_client.py).
            f"{BASE_URL}/playlists/{playlist_id}/items"
            "?limit=100&fields=next,items(added_at,item(id,name,duration_ms,popularity,"
            "explicit,external_urls,album(name,images,release_date),artists(id,name)))"
        )
        while url:
            resp = await self._get(client, url)
            data = resp.json()
            for entry in data.get("items", []):
                track = (entry or {}).get("item")
                if track and track.get("id"):
                    # `added_at` mora na entrada da playlist, não na faixa.
                    tracks.append({**track, "added_at": entry.get("added_at")})
            url = data.get("next")
        return tracks


def is_accessible_playlist(playlist: dict | None, user_id: str | None) -> bool:
    """Se o Spotify permite ler as faixas desta playlist para este usuário."""
    if not playlist:
        return False
    if playlist.get("collaborative"):
        return True
    return user_id is not None and (playlist.get("owner") or {}).get("id") == user_id


async def gather_with_concurrency(limit: int, *coros):
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros))
