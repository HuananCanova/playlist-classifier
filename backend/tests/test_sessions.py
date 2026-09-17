"""Sessões no servidor: o cookie não carrega nada que valha algo sozinho.

Os testes sobem um app ASGI de verdade com o middleware, para cobrir o que só
aparece na troca de cabeçalhos: o cookie emitido, a rotação no login, a remoção
no logout e a leitura de uma sessão expirada ou de outra chave.
"""
import time

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app import db, sessions
from app.config import DEV_SESSION_SECRET, Settings

TOKEN = "BQD-token-secreto-do-spotify"


async def entrar(request: Request):
    request.session.clear()
    sessions.rotate(request)
    request.session["access_token"] = TOKEN
    request.session["me"] = {"id": "eu"}
    return JSONResponse({"ok": True})


async def ler(request: Request):
    return JSONResponse(dict(request.session))


async def anotar(request: Request):
    request.session["nota"] = request.query_params["v"]
    return JSONResponse({"ok": True})


async def sair(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


def _app():
    app = Starlette(
        routes=[
            Route("/entrar", entrar, methods=["POST"]),
            Route("/ler", ler),
            Route("/anotar", anotar, methods=["POST"]),
            Route("/sair", sair, methods=["POST"]),
        ]
    )
    app.add_middleware(sessions.ServerSessionMiddleware, secure=False, same_site="lax")
    return app


@pytest.fixture
def client():
    sessions.reset_cipher()
    transport = httpx.ASGITransport(app=_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _cookie(resp: httpx.Response) -> str:
    return resp.headers["set-cookie"]


async def test_cookie_leva_so_um_id_e_o_banco_so_dados_criptografados(client):
    async with client:
        resp = await client.post("/entrar")
        cookie = _cookie(resp)

        assert cookie.startswith(f"{sessions.COOKIE_NAME}=")
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie
        assert TOKEN not in cookie

        assert (await client.get("/ler")).json()["access_token"] == TOKEN

    row = db.query_one("SELECT id_hash, user_id, data FROM sessions")
    session_id = client.cookies[sessions.COOKIE_NAME]
    assert row["id_hash"] != session_id, "o banco guarda o hash do id, não o id"
    assert TOKEN.encode() not in row["data"]
    assert row["user_id"] == "eu"


async def test_login_troca_o_id_da_sessao(client):
    """Um id plantado antes do login não pode virar a sessão autenticada."""
    async with client:
        await client.post("/anotar?v=anonimo")
        antes = client.cookies[sessions.COOKIE_NAME]

        await client.post("/entrar")
        depois = client.cookies[sessions.COOKIE_NAME]

        assert antes != depois
        assert "nota" not in (await client.get("/ler")).json()

    assert sessions.load(antes) is None, "o id antigo deixa de valer"
    assert db.query_one("SELECT COUNT(*) FROM sessions")[0] == 1


async def test_alteracao_e_gravada_e_leitura_nao_regrava(client, monkeypatch):
    async with client:
        await client.post("/entrar")
        await client.post("/anotar?v=1")
        assert (await client.get("/ler")).json()["nota"] == "1"

        gravacoes = []
        monkeypatch.setattr(sessions, "save", lambda *a: gravacoes.append(a))
        resp = await client.get("/ler")
        assert gravacoes == [] and "set-cookie" not in resp.headers


async def test_logout_apaga_a_sessao_e_o_cookie(client):
    async with client:
        await client.post("/entrar")
        session_id = client.cookies[sessions.COOKIE_NAME]

        resp = await client.post("/sair")

        assert "Max-Age=0" in _cookie(resp)
        assert sessions.load(session_id) is None
        assert (await client.get("/ler")).json() == {}


async def test_sessao_expirada_nao_vale(client, monkeypatch):
    async with client:
        await client.post("/entrar")
        session_id = client.cookies[sessions.COOKIE_NAME]
        client.cookies.clear()
        agora = time.time()
        monkeypatch.setattr(sessions.time, "time", lambda: agora + sessions.SESSION_TTL + 1)

        # Direto no cabeçalho: o próprio httpx descartaria o cookie vencido, e o
        # que se testa é o servidor recusando um cookie que ainda chegue.
        resp = await client.get("/ler", headers={"Cookie": f"{sessions.COOKIE_NAME}={session_id}"})

        assert resp.json() == {}
        assert "Max-Age=0" in _cookie(resp)

    assert sessions.delete_expired() == 0  # a leitura já removeu


async def test_sessao_de_outra_chave_nao_vale(client, monkeypatch):
    """Trocar a chave (ex.: SESSION_SECRET vazado e rotacionado) derruba as sessões."""
    async with client:
        await client.post("/entrar")
        outra = Settings(
            spotify_client_id="x", spotify_client_secret="x", lastfm_api_key="x", session_secret="outro-segredo"
        )
        monkeypatch.setattr(sessions, "get_settings", lambda: outra)
        sessions.reset_cipher()

        assert (await client.get("/ler")).json() == {}


async def test_uso_estende_a_validade(client, monkeypatch):
    async with client:
        await client.post("/entrar")
        session_id = client.cookies[sessions.COOKIE_NAME]
        agora = time.time()
        monkeypatch.setattr(sessions.time, "time", lambda: agora + sessions.TOUCH_EVERY + 5)

        resp = await client.get("/ler")

        assert f"Max-Age={sessions.SESSION_TTL}" in _cookie(resp)
    row = db.query_one("SELECT last_seen FROM sessions WHERE id_hash = ?", (sessions._hash(session_id),))
    assert row["last_seen"] >= agora + sessions.TOUCH_EVERY


def _settings(**kw):
    base = dict(spotify_client_id="x", spotify_client_secret="x", lastfm_api_key="x")
    return Settings(**{**base, **kw})


def test_producao_recusa_o_segredo_de_desenvolvimento():
    with pytest.raises(RuntimeError):
        sessions.check_settings(_settings(session_cookie_secure=True, session_secret=DEV_SESSION_SECRET))
    with pytest.raises(RuntimeError):
        sessions.check_settings(_settings(session_cookie_samesite="none"))

    sessions.check_settings(_settings(session_cookie_secure=True, session_secret="a" * 64))
    sessions.check_settings(_settings())  # desenvolvimento segue subindo
