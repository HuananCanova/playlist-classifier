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


# ── só selo de match confiável ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_label_for_track_checks_match_with_track_page_rule():
    # O detalhe da faixa (que já é pedido para achar o álbum) confere o match
    # com a mesma regra `alta` da página da faixa: título, artista e duração.
    rotas = {
        "/track/7": httpx.Response(
            200, json={"id": 7, "title": "Raro", "artist": {"name": "Zeta"}, "duration": 400, "album": {"id": 70}}
        ),
        "/album/70": httpx.Response(200, json={"id": 70, "label": "Iboga Records"}),
    }
    client, chamadas = _client_contando(rotas)
    async with client:
        selo = await deezer_client.get_label_for_track(client, 7, conferir=("Zeta", "Raro", 401_000))
    assert selo == "Iboga Records"
    assert chamadas == ["/track/7", "/album/70"]


@pytest.mark.parametrize(
    "detalhe",
    [
        # Outro artista: o título bate, mas é outra gravação (outro lançamento).
        {"title": "Raro", "artist": {"name": "Outro"}, "duration": 400},
        # Remix contra a original.
        {"title": "Raro (Remix)", "artist": {"name": "Zeta"}, "duration": 400},
        # Duração longe demais.
        {"title": "Raro", "artist": {"name": "Zeta"}, "duration": 200},
    ],
)
@pytest.mark.asyncio
async def test_label_for_track_refuses_approximate_match(detalhe):
    rotas = {
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}, **detalhe}),
        "/album/70": httpx.Response(200, json={"id": 70, "label": "Iboga Records"}),
    }
    client, chamadas = _client_contando(rotas)
    async with client:
        selo = await deezer_client.get_label_for_track(client, 7, conferir=("Zeta", "Raro", 400_000))
    # Resposta (não falha), mas sem selo: o álbum nem é pedido.
    assert isinstance(selo, deezer_client.NaoConfere) and selo == ""
    assert chamadas == ["/track/7"]
    assert enrichment_store.get_album_label(70) is None


@pytest.mark.asyncio
async def test_label_for_track_with_known_album_skips_track_call():
    rotas = {"/album/70": httpx.Response(200, json={"id": 70, "label": "Iboga Records"})}
    client, chamadas = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7, album_id=70) == "Iboga Records"
    assert chamadas == ["/album/70"]


@pytest.mark.asyncio
async def test_buscar_faixa_returns_album_id():
    def handler(request):
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"data": [{"id": 77, "title": "Raro", "artist": {"name": "Zeta"}}]})
        return httpx.Response(200, json={"id": 77, "bpm": 145, "album": {"id": 700}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        info = await deezer_client.buscar_faixa(client, "Zeta", "Raro")
    assert info["album_id"] == 700


@pytest.mark.asyncio
async def test_label_quota_error_is_failure_and_not_cached():
    # Estouro de cota: HTTP 200 com `error` código 4 — falha, nunca "sem selo".
    cota = httpx.Response(200, json={"error": {"type": "Exception", "message": "Quota limit exceeded", "code": 4}})
    rotas = {"/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}), "/album/70": cota}
    client, _ = _client_contando(rotas)
    async with client:
        assert await deezer_client.get_label_for_track(client, 7) is None
    assert enrichment_store.get_album_label(70) is None

    client, _ = _client_contando({"/track/7": cota})
    async with client:
        assert await deezer_client.get_label_for_track(client, 7, conferir=("Zeta", "Raro", None)) is None
