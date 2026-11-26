"""Selo do lançamento no Deezer. Sem rede — tudo via MockTransport."""
import httpx
import pytest

from app import deezer_client


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
