"""Thin async wrapper around the bits of the Spotify Web API this app needs."""
import asyncio

import httpx

BASE_URL = "https://api.spotify.com/v1"


class SpotifyClient:
    def __init__(self, access_token: str):
        self._headers = {"Authorization": f"Bearer {access_token}"}

    async def get_all_playlists(self, client: httpx.AsyncClient) -> list[dict]:
        playlists: list[dict] = []
        url = f"{BASE_URL}/me/playlists?limit=50"
        while url:
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()
            playlists.extend(data.get("items", []))
            url = data.get("next")
        return playlists

    async def get_playlist(self, client: httpx.AsyncClient, playlist_id: str) -> dict:
        resp = await client.get(f"{BASE_URL}/playlists/{playlist_id}", headers=self._headers)
        resp.raise_for_status()
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
            resp = await client.get(url, headers=self._headers)
            resp.raise_for_status()
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
