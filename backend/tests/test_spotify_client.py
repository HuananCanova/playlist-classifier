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


@pytest.mark.asyncio
async def test_faixas_da_playlist_levam_a_data_em_que_foram_adicionadas():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "added_at" in request.url.params["fields"]
        return httpx.Response(
            200,
            json={
                "items": [
                    {"added_at": "2024-05-01T10:00:00Z", "item": {"id": "t1", "name": "Um"}},
                    {"added_at": "2024-05-02T10:00:00Z", "item": None},
                ],
                "next": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        tracks = await SpotifyClient("token").get_all_playlist_tracks(client, "p1")

    assert tracks == [{"id": "t1", "name": "Um", "added_at": "2024-05-01T10:00:00Z"}]


# ── proteção contra bloqueio ─────────────────────────────────────────────────

def test_chave_do_limite_ignora_o_id():
    """Com o id na chave, cada playlist nova parecia um endpoint livre."""
    from app.spotify_client import _throttle_key

    assert _throttle_key("https://api.spotify.com/v1/playlists/abc/items?limit=100") == "/v1/playlists/{id}/items"
    assert _throttle_key("https://api.spotify.com/v1/playlists/xyz/items") == "/v1/playlists/{id}/items"
    assert _throttle_key("https://api.spotify.com/v1/me/playlists?limit=50") == "/v1/me/playlists"


@pytest.mark.asyncio
async def test_espera_longa_bloqueia_todas_as_rotas_e_fica_em_disco(spotify_state_tmp, monkeypatch):
    chamadas = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        return httpx.Response(429, headers={"Retry-After": "65527"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        spotify = SpotifyClient("token")
        with pytest.raises(httpx.HTTPStatusError):
            await spotify.get_playlist(client, "p1")
        # Outra rota, outro id: nada sai para a rede.
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await spotify.get_me(client)

    assert chamadas == ["/v1/playlists/p1"], "uma espera longa não se repete, e bloqueia o resto"
    assert int(exc.value.response.headers["Retry-After"]) > 60_000

    # "Reinício": estado em memória zerado, bloqueio lido do disco.
    monkeypatch.setattr(spotify_state_tmp, "_global_until", None)
    assert spotify_state_tmp.global_block_remaining() > 60_000
    assert spotify_state_tmp.throttle_state()["global_block_seconds"] > 60_000


@pytest.mark.asyncio
async def test_espera_curta_vale_so_para_a_rota(spotify_state_tmp, monkeypatch):
    monkeypatch.setattr("app.spotify_client.MAX_RETRIES", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/playlists"):
            return httpx.Response(429, headers={"Retry-After": "20"})
        return httpx.Response(200, json={"id": "eu"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        spotify = SpotifyClient("token")
        with pytest.raises(httpx.HTTPStatusError):
            await spotify.get_playlist(client, "p1")
        assert (await spotify.get_me(client))["id"] == "eu"

    assert spotify_state_tmp.global_block_remaining() is None


@pytest.mark.asyncio
async def test_listagem_com_usuario_conhecido_nao_chama_me():
    caminhos = []

    def handler(request: httpx.Request) -> httpx.Response:
        caminhos.append(request.url.path)
        return httpx.Response(200, json={"items": [_pl("minha", "eu")], "next": None})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        playlists = await SpotifyClient("token").get_all_playlists(client, user_id="eu")

    assert caminhos == ["/v1/me/playlists"]
    assert [p["id"] for p in playlists] == ["minha"]
