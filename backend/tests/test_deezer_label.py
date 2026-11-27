"""Selo do lançamento no Deezer. Sem rede — tudo via MockTransport."""
import httpx
import pytest

from app import deezer_client, enrichment_store


def _client(rotas: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return rotas.get(request.url.path, httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_returns_album_label():
    rotas = {
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70, "label": " Iboga Records "}),
    }
    async with _client(rotas) as client:
        assert await deezer_client.get_track_label(client, 7) == "Iboga Records"


@pytest.mark.asyncio
async def test_empty_string_when_album_has_no_label():
    rotas = {
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70}),
    }
    async with _client(rotas) as client:
        assert await deezer_client.get_track_label(client, 7) == ""


@pytest.mark.asyncio
async def test_none_when_album_call_fails():
    rotas = {"/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}})}
    async with _client(rotas) as client:
        assert await deezer_client.get_track_label(client, 7) is None


@pytest.mark.asyncio
async def test_none_when_deezer_answers_error_object():
    rotas = {"/track/7": httpx.Response(200, json={"error": {"code": 800}})}
    async with _client(rotas) as client:
        assert await deezer_client.get_track_label(client, 7) is None


def _client_contando(rotas: dict[str, httpx.Response]) -> tuple[httpx.AsyncClient, list[str]]:
    chamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        chamadas.append(request.url.path)
        return rotas.get(request.url.path, httpx.Response(404))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), chamadas


@pytest.mark.asyncio
async def test_label_for_track_fetches_and_caches_album():
    rotas = {
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}),
        "/track/8": httpx.Response(200, json={"id": 8, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70, "label": " Iboga Records "}),
    }
    client, chamadas = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) == "Iboga Records"
        assert chamadas == ["/track/7", "/album/70"]
        # Outra faixa do mesmo álbum: o selo vem do banco, sem pedir o álbum.
        assert await deezer_client.get_label_for_track(client, 8) == "Iboga Records"
        assert chamadas == ["/track/7", "/album/70", "/track/8"]
    assert enrichment_store.get_album_label(70) == "Iboga Records"


@pytest.mark.asyncio
async def test_label_for_track_caches_empty_label():
    rotas = {
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70}),
    }
    client, chamadas = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) == ""
        assert await deezer_client.get_label_for_track(client, 7) == ""
    assert chamadas.count("/album/70") == 1
    assert enrichment_store.get_album_label(70) == ""


@pytest.mark.asyncio
async def test_label_for_track_failure_is_not_cached():
    rotas = {"/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}})}
    client, _ = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) is None
    assert enrichment_store.get_album_label(70) is None

    # A próxima tentativa pergunta de novo e, dando certo, grava.
    rotas["/album/70"] = httpx.Response(200, json={"id": 70, "label": "Iboga Records"})
    client, chamadas = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) == "Iboga Records"
    assert "/album/70" in chamadas


@pytest.mark.asyncio
async def test_label_for_track_none_when_track_call_fails():
    client, chamadas = _client_contando({"/track/7": httpx.Response(500)})
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) is None
    assert chamadas == ["/track/7"]
