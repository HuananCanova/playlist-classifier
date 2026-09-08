"""Thin async wrapper around the bits of the Spotify Web API this app needs."""
import asyncio
import logging

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


class SpotifyClient:
    def __init__(self, access_token: str):
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def _get(self, client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        """GET com repetição em 429, respeitando o Retry-After do Spotify."""
        for attempt in range(MAX_RETRIES + 1):
            resp = await client.get(url, headers=self._headers, **kwargs)

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
