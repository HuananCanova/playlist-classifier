"""`congelar_subgeneros --so-selo`: só o selo muda. Sem rede — MockTransport."""
import httpx
import pytest

from evals import congelar_subgeneros as congelar

REF = {"id": "x", "artista": "Artifact303", "titulo": "Feelings"}
ANTIGO = {
    "id": "x",
    "faixa": "Artifact303 — Feelings",
    "referencia": "https://psytranceguide.com",
    "subgenero": "goa trance",
    "artista": [["goa", 100]],
    "faixa_tags": [],
    "bpm": 144.1,
    "incompleto": True,
}
ACHADA = {"data": [{"id": 7, "title": "Feelings", "artist": {"name": "Artifact303"}}]}


@pytest.fixture(autouse=True)
def sem_pausa(monkeypatch):
    monkeypatch.setattr(congelar, "PAUSA_S", 0)


def _client(rotas: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return rotas.get(request.url.path, httpx.Response(500))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_preenche_so_o_selo_e_mantem_o_resto():
    rotas = {
        "/search": httpx.Response(200, json=ACHADA),
        "/track/7": httpx.Response(200, json={"id": 7, "bpm": 0, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70, "label": "Suntrip Records"}),
    }
    async with _client(rotas) as client:
        caso = await congelar.so_selo_caso(client, REF, ANTIGO)

    # O Deezer agora diz bpm 0, mas o BPM congelado fica; `incompleto` também.
    assert caso == {**ANTIGO, "selo": "Suntrip Records"}
    assert list(caso).index("selo") == list(caso).index("bpm") + 1


@pytest.mark.asyncio
async def test_falha_mantem_o_selo_anterior():
    rotas = {"/search": httpx.Response(200, json=ACHADA)}  # detalhe e álbum falham
    async with _client(rotas) as client:
        caso = await congelar.so_selo_caso(client, REF, {**ANTIGO, "selo": "Suntrip Records"})
    assert caso["selo"] == "Suntrip Records"


@pytest.mark.asyncio
async def test_falha_sem_selo_anterior_fica_null():
    async with _client({}) as client:  # nem a busca responde
        caso = await congelar.so_selo_caso(client, REF, ANTIGO)
    assert caso["selo"] is None
    assert {k: v for k, v in caso.items() if k != "selo"} == ANTIGO


@pytest.mark.asyncio
async def test_faixa_fora_do_deezer_e_resposta():
    rotas = {"/search": httpx.Response(200, json={"data": []})}
    async with _client(rotas) as client:
        caso = await congelar.so_selo_caso(client, REF, {**ANTIGO, "selo": "Velho"})
    assert caso["selo"] is None


@pytest.mark.asyncio
async def test_album_sem_selo_vira_string_vazia():
    rotas = {
        "/search": httpx.Response(200, json=ACHADA),
        "/track/7": httpx.Response(200, json={"id": 7, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70}),
    }
    async with _client(rotas) as client:
        caso = await congelar.so_selo_caso(client, REF, ANTIGO)
    assert caso["selo"] == ""


def test_comentario_dos_limiares_sobrevive():
    texto = "# cabeçalho\n\nlimiares:\n  # corrida de ontem\n  # e a de hoje\n  max_incerto: 1.0\ncasos: []\n"
    assert congelar._comentario_dos_limiares(texto) == "  # corrida de ontem\n  # e a de hoje\n"


# ── congelamento completo ────────────────────────────────────────────────────


@pytest.fixture
def lastfm_ok(monkeypatch):
    from app.taxonomy import Tag

    async def artista(client, nome, limit=8):
        return [Tag("goa", 100.0)]

    async def faixa(client, nome, titulo, limit=10):
        return []

    monkeypatch.setattr(congelar.lastfm_client, "get_artist_tags", artista)
    monkeypatch.setattr(congelar.lastfm_client, "get_track_tags", faixa)


REF_COMPLETA = {**REF, "referencia": "https://psytranceguide.com", "subgenero": "goa trance"}


@pytest.mark.asyncio
async def test_congelar_selo_que_falha_sem_selo_anterior_fica_incompleto(lastfm_ok):
    # Caso congelado antes de existir selo: falhar agora não pode virar
    # "sem selo" silencioso.
    antigo = {k: v for k, v in ANTIGO.items() if k != "incompleto"}
    rotas = {
        "/search": httpx.Response(200, json=ACHADA),
        "/track/7": httpx.Response(200, json={"id": 7, "bpm": 144.1, "album": {"id": 70}}),
    }  # o álbum falha
    async with _client(rotas) as client:
        caso = await congelar.congelar_caso(client, REF_COMPLETA, antigo)
    assert caso["selo"] is None and caso["incompleto"] is True


@pytest.mark.asyncio
async def test_congelar_selo_que_falha_mantem_o_anterior(lastfm_ok):
    antigo = {**{k: v for k, v in ANTIGO.items() if k != "incompleto"}, "selo": "Suntrip Records"}
    rotas = {
        "/search": httpx.Response(200, json=ACHADA),
        "/track/7": httpx.Response(200, json={"id": 7, "bpm": 144.1, "album": {"id": 70}}),
    }
    async with _client(rotas) as client:
        caso = await congelar.congelar_caso(client, REF_COMPLETA, antigo)
    assert caso["selo"] == "Suntrip Records" and "incompleto" not in caso


@pytest.mark.asyncio
async def test_congelar_reaproveita_a_busca_do_bpm_para_o_selo(lastfm_ok, monkeypatch):
    buscas: list = []
    original = congelar.deezer_client.get_track_info

    async def contando(client, artista, titulo):
        buscas.append(titulo)
        return await original(client, artista, titulo)

    monkeypatch.setattr(congelar.deezer_client, "get_track_info", contando)
    rotas = {
        "/search": httpx.Response(200, json=ACHADA),
        "/track/7": httpx.Response(200, json={"id": 7, "bpm": 144.1, "album": {"id": 70}}),
        "/album/70": httpx.Response(200, json={"id": 70, "label": "Suntrip Records"}),
    }
    async with _client(rotas) as client:
        caso = await congelar.congelar_caso(client, REF_COMPLETA, None)
    assert buscas == ["Feelings"]
    assert (caso["bpm"], caso["selo"]) == (144.1, "Suntrip Records") and "incompleto" not in caso


@pytest.mark.asyncio
async def test_so_selo_que_falha_sem_selo_anterior_fica_incompleto():
    antigo = {k: v for k, v in ANTIGO.items() if k != "incompleto"}
    async with _client({}) as client:  # nem a busca responde
        caso = await congelar.so_selo_caso(client, REF, antigo)
    assert caso["selo"] is None and caso["incompleto"] is True
