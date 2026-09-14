"""Filtro de playlists acessíveis.

Desde fevereiro de 2026 o Spotify só devolve as faixas de playlists do próprio
usuário ou colaborativas; as que ele apenas segue respondem 403 ao abrir.
"""
import httpx
import pytest

from app.spotify_client import SpotifyClient, is_accessible_playlist


def _pl(pid, owner_id, collaborative=False):
    return {"id": pid, "owner": {"id": owner_id}, "collaborative": collaborative}


def test_playlist_do_usuario_e_acessivel():
    assert is_accessible_playlist(_pl("a", "eu"), "eu")


def test_playlist_de_outro_usuario_fica_de_fora():
    assert not is_accessible_playlist(_pl("a", "spotify"), "eu")


def test_colaborativa_de_outro_usuario_e_acessivel():
    assert is_accessible_playlist(_pl("a", "amigo", collaborative=True), "eu")


def test_sem_usuario_ou_playlist_nula_nao_passa():
    assert not is_accessible_playlist(_pl("a", "eu"), None)
    assert not is_accessible_playlist(None, "eu")


@pytest.mark.asyncio
async def test_get_all_playlists_filtra_em_todas_as_paginas():
    paginas = {
        "/v1/me": {"id": "eu"},
        "/v1/me/playlists": {
            "items": [_pl("minha", "eu"), _pl("seguida", "spotify"), None],
            "next": "https://api.spotify.com/v1/me/playlists/page2",
        },
        "/v1/me/playlists/page2": {
            "items": [_pl("colab", "amigo", collaborative=True), _pl("outra", "fulano")],
            "next": None,
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=paginas[request.url.path])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        playlists = await SpotifyClient("token").get_all_playlists(client)

    assert [p["id"] for p in playlists] == ["minha", "colab"]
