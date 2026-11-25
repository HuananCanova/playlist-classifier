"""Cliente do Discogs: estilos do lançamento. Sem rede — tudo via MockTransport."""
import httpx
import pytest

from app import discogs_client


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _resposta(results: list[dict]):
    return lambda request: httpx.Response(200, json={"results": results})


@pytest.mark.asyncio
async def test_returns_styles_of_matching_release():
    handler = _resposta(
        [{"title": "Porat - Ritual Resonance", "style": ["Psy-Trance", "Progressive Trance"]}]
    )
    async with _client(handler) as client:
        estilos = await discogs_client.get_release_styles(client, "Porat", "Ritual Resonance", "tok")
    assert estilos == ["Psy-Trance", "Progressive Trance"]


@pytest.mark.asyncio
async def test_empty_list_when_release_has_no_styles():
    handler = _resposta([{"title": "Porat - Ritual Resonance"}])
    async with _client(handler) as client:
        assert await discogs_client.get_release_styles(client, "Porat", "Ritual Resonance", "tok") == []


@pytest.mark.asyncio
async def test_none_when_no_result_matches():
    handler = _resposta([{"title": "Porat - Outro Disco", "style": ["Psy-Trance"]}])
    async with _client(handler) as client:
        assert await discogs_client.get_release_styles(client, "Porat", "Ritual Resonance", "tok") is None


@pytest.mark.asyncio
async def test_none_on_http_error():
    async with _client(lambda request: httpx.Response(500)) as client:
        assert await discogs_client.get_release_styles(client, "Porat", "Ritual Resonance", "tok") is None


@pytest.mark.asyncio
async def test_sends_token_header():
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(200, json={"results": []})

    async with _client(handler) as client:
        await discogs_client.get_release_styles(client, "Porat", "Ritual Resonance", "segredo")
    req = vistos[0]
    assert req.headers["Authorization"] == "Discogs token=segredo"
    assert req.headers["User-Agent"]
    assert req.url.params["artist"] == "Porat"
    assert req.url.params["release_title"] == "Ritual Resonance"
    assert req.url.params["type"] == "release"
