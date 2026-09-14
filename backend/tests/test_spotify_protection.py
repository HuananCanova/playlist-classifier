"""Proteção contra bloqueio do Spotify fora do cliente HTTP.

O `/me` do login e a listagem de playlists eram as chamadas que continuavam
saindo durante um bloqueio: uma a cada página aberta. Estes testes garantem que
elas saem da sessão e do disco quando podem.
"""
import time

import httpx
import pytest
from fastapi import HTTPException

from app import auth, playlists
from app.models import PlaylistSummary
from app.profile_stats import build_index_stats


class FakeRequest:
    def __init__(self, session=None):
        self.session = session or {}


@pytest.fixture
def me_do_spotify(monkeypatch):
    chamadas = []

    async def get_me(self, client):
        chamadas.append("me")
        return {"id": "eu", "display_name": "Eu", "images": [{"url": "http://img"}], "followers": {"total": 3}}

    monkeypatch.setattr(auth.SpotifyClient, "get_me", get_me)
    return chamadas


async def test_perfil_do_login_sai_da_sessao(me_do_spotify):
    request = FakeRequest()

    primeiro = await auth.get_me(request, "tok")
    segundo = await auth.get_me(request, "tok")

    assert primeiro["display_name"] == "Eu" and segundo["id"] == "eu"
    assert me_do_spotify == ["me"], "a segunda página aberta não pode chamar o Spotify"


async def test_perfil_expirado_e_renovado(me_do_spotify):
    request = FakeRequest({"me": {"id": "eu", "fetched_at": time.time() - auth.ME_MAX_AGE - 1}})
    await auth.get_me(request, "tok")
    assert me_do_spotify == ["me"]


async def test_bloqueado_usa_a_sessao_e_nao_desloga(me_do_spotify, spotify_state_tmp):
    spotify_state_tmp._set_global_block(3600)
    velho = {"id": "eu", "display_name": "Eu", "fetched_at": 0}

    assert (await auth.get_me(FakeRequest({"me": velho}), "tok"))["id"] == "eu"
    # Sem nada guardado, devolve vazio — nunca um erro que derrube o login.
    assert await auth.get_me(FakeRequest(), "tok") == {}
    assert me_do_spotify == []


async def test_falha_do_spotify_nao_derruba_o_login(monkeypatch):
    async def falha(self, client):
        request = httpx.Request("GET", "https://api.spotify.com/v1/me")
        raise httpx.HTTPStatusError("500", request=request, response=httpx.Response(500, request=request))

    monkeypatch.setattr(auth.SpotifyClient, "get_me", falha)
    assert await auth.get_me(FakeRequest(), "tok") == {}


# ── listagem guardada em disco ───────────────────────────────────────────────

@pytest.fixture
def listagem(monkeypatch):
    playlists.user_playlists_cache.clear()
    estado = {"chamadas": 0, "falhar": False}

    async def token(request):
        return "tok"

    async def get_all(self, client, user_id=None):
        estado["chamadas"] += 1
        if estado["falhar"]:
            request = httpx.Request("GET", "https://api.spotify.com/v1/me/playlists")
            response = httpx.Response(429, headers={"Retry-After": "65527"}, request=request)
            raise httpx.HTTPStatusError("429", request=request, response=response)
        return [{"id": "p1", "name": "Uma", "snapshot_id": "s", "items": {"total": 4}, "owner": {"id": "eu"}}]

    monkeypatch.setattr(playlists, "get_valid_access_token", token)
    monkeypatch.setattr(playlists.SpotifyClient, "get_all_playlists", get_all)
    yield estado
    playlists.user_playlists_cache.clear()


def _request():
    return FakeRequest({"refresh_token": "r", "me": {"id": "eu"}})


async def test_reinicio_reaproveita_a_listagem_recente(listagem):
    await playlists.get_playlist_summaries(_request())
    playlists.user_playlists_cache.clear()  # simula o reinício do backend

    resultado = await playlists.get_playlist_summaries(_request())

    assert [p.id for p in resultado] == ["p1"]
    assert listagem["chamadas"] == 1


async def test_bloqueado_serve_a_ultima_listagem(listagem):
    await playlists.get_playlist_summaries(_request())
    listagem["falhar"] = True

    resultado = await playlists.get_playlist_summaries(_request(), refresh=True)

    assert [p.id for p in resultado] == ["p1"]


async def test_bloqueado_sem_listagem_explica_quanto_falta(listagem):
    listagem["falhar"] = True
    with pytest.raises(HTTPException) as exc:
        await playlists.get_playlist_summaries(_request())
    assert exc.value.status_code == 429
    assert "~18 h" in exc.value.detail


def test_texto_de_espera():
    assert playlists.wait_text(40) == "~40 s"
    assert playlists.wait_text(1200).startswith("~20 min (até ")
    assert playlists.wait_text(65527).startswith("~18 h (até ")


# ── estatísticas do índice ───────────────────────────────────────────────────

def test_estatisticas_do_indice():
    stats = build_index_stats(
        [
            {"artistas": "Slowdive", "tags": "shoegaze, dream pop"},
            {"artistas": "Slowdive, Beach House", "tags": "Dream Pop"},
            {"artistas": "", "tags": ""},
        ]
    )
    assert stats["tracks"] == 3
    assert stats["unique_artists"] == 2
    assert stats["top_artists"][0] == {"name": "Slowdive", "tracks": 2}
    assert stats["top_tags"][0] == {"label": "dream pop", "count": 2}
    assert build_index_stats([]) is None
