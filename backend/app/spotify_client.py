"""Thin async wrapper around the bits of the Spotify Web API this app needs."""
import asyncio
import logging
import time
import urllib.parse

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


# Até quando cada endpoint está bloqueado, por caminho ("/v1/me/playlists").
# O Spotify limita por endpoint, então bloquear o app inteiro seria exagero.
_throttled_until: dict[str, float] = {}

# Quantas chamadas realmente saíram para o Spotify desde que o processo subiu.
# Serve para o health check dizer se o "não há bloqueio" é uma informação ou
# apenas ausência de informação.
_calls_since_boot = 0


def _throttle_key(url: str) -> str:
    return urllib.parse.urlparse(str(url)).path


def _remember_throttle(url: str, resp: httpx.Response) -> None:
    try:
        wait = float(resp.headers.get("Retry-After", 1))
    except ValueError:
        wait = 1.0
    _throttled_until[_throttle_key(url)] = time.time() + wait
    logger.warning("Spotify bloqueou %s por %.0fs", _throttle_key(url), wait)


def _raise_if_throttled(url: str) -> None:
    """Falha na hora, sem chamar o Spotify, enquanto o bloqueio não expira."""
    remaining = _throttled_until.get(_throttle_key(url), 0) - time.time()
    if remaining <= 0:
        return

    request = httpx.Request("GET", url)
    response = httpx.Response(
        429, headers={"Retry-After": str(int(remaining))}, request=request
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
    return {
        "checked": _calls_since_boot > 0,
        "calls_since_boot": _calls_since_boot,
        "blocked": blocked,
        "summary": (
            "sem contato com o Spotify desde o restart — recarregue a página para descobrir"
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

    async def get_all_playlists(self, client: httpx.AsyncClient) -> list[dict]:
        playlists: list[dict] = []
        url = f"{BASE_URL}/me/playlists?limit=50"
        while url:
            resp = await self._get(client, url)
            data = resp.json()
            playlists.extend(data.get("items", []))
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
            "?limit=100&fields=next,items(item(id,name,duration_ms,popularity,"
            "external_urls,album(name,images),artists(id,name)))"
        )
        while url:
            resp = await self._get(client, url)
            data = resp.json()
            for entry in data.get("items", []):
                track = (entry or {}).get("item")
                if track and track.get("id"):
                    tracks.append(track)
            url = data.get("next")
        return tracks


async def gather_with_concurrency(limit: int, *coros):
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_run(c) for c in coros))
