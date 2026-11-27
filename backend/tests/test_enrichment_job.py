"""O job que enche `track_evidence` para o acervo — sem Spotify, sem rede."""
import asyncio

import httpx
import pytest

from app import deezer_client, enrichment_job, evidence_store, lastfm_client
from app.deezer_client import NotFound
from app.lastfm_client import NoAnswer
from app.taxonomy import Tag

CONTA = "spotify:eu"

SEM_MATCH = {"deezer_id": None, "bpm": None, "preview_url": None, "deezer_url": None}


@pytest.fixture(autouse=True)
def job_limpo(monkeypatch):
    # Locks do asyncio se prendem ao loop do teste; um novo por teste.
    monkeypatch.setattr(enrichment_job, "_jobs", {})
    monkeypatch.setattr(enrichment_job, "_lock", asyncio.Lock())


def _t(tid, genres=(), artists=("Artista",)):
    return {"id": tid, "name": f"Faixa {tid}", "artists": list(artists), "genres": list(genres)}


def _digests(*tracks):
    return {"p1": {"playlist": {"id": "p1"}, "tracks": list(tracks)}}


class Fontes:
    """Last.fm e Deezer falsos que contam o que foi pedido."""

    def __init__(self, monkeypatch):
        self.artistas: list[str] = []
        self.faixas: list[str] = []
        self.deezer: list[tuple[str, str]] = []
        self.falha_faixa: set[str] = set()
        self.espera: asyncio.Event | None = None
        self.deezer_resposta = {"deezer_id": 7, "bpm": 145.0, "preview_url": None, "deezer_url": "u"}
        self.selos: list[int] = []
        self.conferidos: list = []
        # str = resposta do Deezer ("" = álbum sem selo); None = falha.
        self.selo_resposta: str | None = "Iboga Records"
        monkeypatch.setattr(lastfm_client, "get_artist_tags", self._artist)
        monkeypatch.setattr(lastfm_client, "get_track_tags", self._track)
        monkeypatch.setattr(deezer_client, "get_many", self._deezer)
        monkeypatch.setattr(deezer_client, "get_label_for_track", self._selo)

    async def _artist(self, client, artist, limit=8):
        self.artistas.append(artist)
        return [Tag(f"tag de {artist}", 80.0)]

    async def _track(self, client, artist, track, limit=10):
        self.faixas.append(track)
        if self.espera is not None:
            await self.espera.wait()
        if track in self.falha_faixa:
            raise httpx.ConnectError("sem rede")
        return [Tag("psytrance", 100.0)]

    async def _deezer(self, client, pairs):
        self.deezer.extend(pairs)
        return [self.deezer_resposta for _ in pairs]

    async def _selo(self, client, deezer_id, *, conferir=None, album_id=None):
        self.selos.append(deezer_id)
        self.conferidos.append(conferir)
        return self.selo_resposta


@pytest.fixture
def fontes(monkeypatch):
    return Fontes(monkeypatch)


async def _rodar(digests):
    await enrichment_job.start(CONTA, digests)
    await enrichment_job.wait(CONTA)


def test_pending_orders_psy_first():
    digests = _digests(_t("a", ["rock"]), _t("b", ["psytrance"]), _t("c", []), _t("b", ["psytrance"]))
    assert [t["id"] for t in enrichment_job.pending_tracks(digests)] == ["b", "a", "c"]


async def test_job_fills_evidence(fontes):
    await _rodar(_digests(_t("a", ["psytrance"], artists=("X", "Y"))))

    ev = evidence_store.get_many(["a"])["a"]
    # Cada artista creditado é buscado separado; as tags se juntam na evidência.
    assert sorted(fontes.artistas) == ["X", "Y"]
    assert {t.name for t in ev.artist_tags} == {"tag de X", "tag de Y"}
    assert ev.track_tags == [Tag("psytrance", 100.0)]
    assert (ev.bpm, ev.deezer_id) == (145.0, 7)
    assert ev.deezer_checked_at is not None
    progress = enrichment_job.progress_dict(CONTA)
    assert (progress["running"], progress["total"], progress["done"], progress["errors"]) == (False, 1, 1, [])


async def test_failed_lookup_not_stored_and_retried_next_run(fontes):
    digests = _digests(_t("a", ["psytrance"]), _t("b", ["psytrance"]))
    fontes.falha_faixa = {"Faixa b"}
    await _rodar(digests)

    assert evidence_store.get_many(["b"])["b"].track_tags is None
    assert evidence_store.get_many(["a"])["a"].track_tags is not None
    assert len(enrichment_job.progress_dict(CONTA)["errors"]) == 1
    assert evidence_store.missing(["a", "b"]) == ["b"]

    fontes.falha_faixa = set()
    fontes.faixas.clear()
    await _rodar(digests)
    assert fontes.faixas == ["Faixa b"]  # só o que falhou
    assert evidence_store.get_many(["b"])["b"].track_tags == [Tag("psytrance", 100.0)]
    assert evidence_store.missing(["a", "b"]) == []


async def test_noanswer_is_not_stored_as_empty(fontes, monkeypatch):
    async def sem_resposta(client, artist, limit=8):
        return NoAnswer()

    monkeypatch.setattr(lastfm_client, "get_artist_tags", sem_resposta)
    await _rodar(_digests(_t("a")))
    assert evidence_store.get_many(["a"])["a"].artist_tags is None
    assert enrichment_job.progress_dict(CONTA)["errors"]


async def test_restart_skips_completed_tracks(fontes):
    digests = _digests(_t("a"), _t("b"))
    await _rodar(digests)
    fontes.artistas.clear()
    fontes.faixas.clear()
    fontes.deezer.clear()

    await _rodar(digests)
    assert (fontes.artistas, fontes.faixas, fontes.deezer) == ([], [], [])
    assert enrichment_job.progress_dict(CONTA)["pending"] == 0


async def test_only_missing_sources_are_fetched(fontes):
    # Já tem tags de artista e de faixa; só falta o Deezer.
    evidence_store.put(evidence_store.TrackEvidence("a", [Tag("x", 1.0)], [Tag("y", 1.0)]))
    await _rodar(_digests(_t("a")))
    assert (fontes.artistas, fontes.faixas) == ([], [])
    assert fontes.deezer == [("Artista", "Faixa a")]


async def test_deezer_not_found_is_recorded_but_failure_is_not(fontes):
    fontes.deezer_resposta = NotFound(SEM_MATCH)
    await _rodar(_digests(_t("a")))
    ev = evidence_store.get_many(["a"])["a"]
    assert ev.deezer_checked_at is not None and ev.bpm is None and ev.deezer_id is None

    fontes.deezer_resposta = dict(SEM_MATCH)  # falha: dict vazio comum
    await _rodar(_digests(_t("b")))
    assert evidence_store.get_many(["b"])["b"].deezer_checked_at is None
    assert evidence_store.missing(["b"]) == ["b"]


async def test_job_reclassifies_the_account_playlists(fontes, monkeypatch):
    chamadas = []
    monkeypatch.setattr(enrichment_job.reclassify, "account", lambda ids: chamadas.append(ids) or {})
    await _rodar(_digests(_t("a")))
    assert chamadas == [["p1"]]


async def test_second_start_while_running_returns_same_progress(fontes):
    fontes.espera = asyncio.Event()
    digests = _digests(_t("a"))
    primeiro = await enrichment_job.start(CONTA, digests)
    segundo = await enrichment_job.start(CONTA, digests)
    assert primeiro is segundo and primeiro.running
    fontes.espera.set()
    await enrichment_job.wait(CONTA)
    assert not primeiro.running


def test_estimated_minutes_rounds_up_with_min_one():
    assert enrichment_job.estimate_minutes(0) == 0
    assert enrichment_job.estimate_minutes(1) == 1
    assert enrichment_job.estimate_minutes(enrichment_job.TRACKS_PER_MINUTE + 1) == 2


async def test_no_spotify_calls(fontes, monkeypatch):
    from app import genre_analysis, playlists, spotify_client

    def proibido(*a, **k):
        raise AssertionError("o job não pode chamar o Spotify")

    for modulo in (spotify_client, genre_analysis, playlists):
        monkeypatch.setattr(modulo, "SpotifyClient", proibido)
    await _rodar(_digests(_t("a")))
    assert enrichment_job.progress_dict(CONTA)["errors"] == []
    assert evidence_store.missing(["a"]) == []


# ── selo (Deezer) ────────────────────────────────────────────────────────────


async def test_job_fills_label(fontes):
    await _rodar(_digests(_t("a", ["psytrance"])))
    ev = evidence_store.get_many(["a"])["a"]
    # O selo é pedido pelo deezer_id que a busca acabou de achar.
    assert fontes.selos == [7]
    assert ev.label == "Iboga Records" and ev.label_checked_at is not None
    assert evidence_store.missing(["a"]) == []


async def test_album_without_label_is_recorded(fontes):
    fontes.selo_resposta = ""
    await _rodar(_digests(_t("a")))
    ev = evidence_store.get_many(["a"])["a"]
    assert ev.label == "" and ev.label_checked_at is not None
    assert evidence_store.missing(["a"]) == []


async def test_failed_label_not_stored_and_retried_next_run(fontes):
    digests = _digests(_t("a"))
    fontes.selo_resposta = None
    await _rodar(digests)

    ev = evidence_store.get_many(["a"])["a"]
    assert ev.label is None and ev.label_checked_at is None
    assert ev.deezer_id == 7  # o resto da evidência foi guardado
    assert enrichment_job.progress_dict(CONTA)["errors"] == ["Faixa a: selo (Deezer)"]
    assert evidence_store.missing(["a"]) == ["a"]

    fontes.selo_resposta = "Iboga Records"
    fontes.artistas.clear()
    fontes.faixas.clear()
    fontes.deezer.clear()
    fontes.selos.clear()
    await _rodar(digests)
    assert (fontes.artistas, fontes.faixas, fontes.deezer) == ([], [], [])
    assert fontes.selos == [7]
    assert evidence_store.get_many(["a"])["a"].label == "Iboga Records"
    assert evidence_store.missing(["a"]) == []


async def test_stored_match_without_label_gets_only_the_label_call(fontes):
    # Evidência anterior ao selo: tags e Deezer completos, selo nunca perguntado.
    evidence_store.put(
        evidence_store.TrackEvidence(
            "a", [Tag("x", 1.0)], [Tag("y", 1.0)], bpm=146.0, deezer_id=99, deezer_checked_at=1.0
        )
    )
    await _rodar(_digests(_t("a")))
    assert (fontes.artistas, fontes.faixas, fontes.deezer) == ([], [], [])
    assert fontes.selos == [99]
    ev = evidence_store.get_many(["a"])["a"]
    assert (ev.label, ev.bpm, ev.deezer_id) == ("Iboga Records", 146.0, 99)


async def test_no_label_call_without_deezer_match(fontes):
    fontes.deezer_resposta = NotFound(SEM_MATCH)
    await _rodar(_digests(_t("a")))
    assert fontes.selos == []
    assert evidence_store.missing(["a"]) == []


async def test_job_label_checks_match_and_records_origin(fontes):
    track = {**_t("a"), "duration_ms": 401_000}
    await _rodar(_digests(track))
    # O selo só vale para um match `alta`: o job manda conferir com a faixa.
    assert fontes.conferidos == [("Artista", "Faixa a", 401_000)]
    assert evidence_store.get_many(["a"])["a"].label_deezer_id == 7


async def test_job_unconfirmed_match_is_answer_without_label(fontes):
    fontes.selo_resposta = deezer_client.NaoConfere()
    await _rodar(_digests(_t("a")))
    ev = evidence_store.get_many(["a"])["a"]
    # Consultado (não volta à fila), mas sem selo — e sem erro.
    assert ev.label is None and ev.label_checked_at is not None and ev.label_deezer_id == 7
    assert evidence_store.missing(["a"]) == []
    assert enrichment_job.progress_dict(CONTA)["errors"] == []


async def test_label_from_another_deezer_id_is_refetched(fontes):
    evidence_store.put(
        evidence_store.TrackEvidence(
            "a", [Tag("x", 1.0)], [Tag("y", 1.0)], deezer_id=99, deezer_checked_at=1.0,
            label="Outro Selo", label_checked_at=1.0, label_deezer_id=5,
        )
    )
    await _rodar(_digests(_t("a")))
    assert (fontes.deezer, fontes.selos) == ([], [99])
    ev = evidence_store.get_many(["a"])["a"]
    assert (ev.label, ev.label_deezer_id) == ("Iboga Records", 99)


# ── sinal "não achou" do Deezer ──────────────────────────────────────────────


def _cliente_deezer(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_deezer_distinguishes_not_found_from_failure():
    sem_resultado = _cliente_deezer(lambda req: httpx.Response(200, json={"data": []}))
    info = await deezer_client.get_track_info(sem_resultado, "Ninguem", "Nada")
    assert isinstance(info, NotFound)
    assert info == SEM_MATCH

    fora_do_ar = _cliente_deezer(lambda req: httpx.Response(503))
    info = await deezer_client.get_track_info(fora_do_ar, "Outro", "Tambem")
    assert not isinstance(info, NotFound)
    assert info["deezer_id"] is None


async def test_deezer_not_found_stays_not_found_from_the_store():
    sem_resultado = _cliente_deezer(lambda req: httpx.Response(200, json={"data": []}))
    await deezer_client.get_track_info(sem_resultado, "Ninguem", "Nada")
    deezer_client.deezer_track_cache.clear()
    info = await deezer_client.get_track_info(sem_resultado, "Ninguem", "Nada")
    assert isinstance(info, NotFound)


# ── rotas ────────────────────────────────────────────────────────────────────


@pytest.fixture
def rotas(monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app import subgenres

    async def token(request):
        return "t"

    async def listagem(request, refresh=False):
        if estado["429"]:
            raise HTTPException(status_code=429, detail="bloqueado")
        return []

    estado = {"429": False}
    monkeypatch.setattr(subgenres, "get_valid_access_token", token)
    monkeypatch.setattr(subgenres, "get_playlist_summaries", listagem)
    monkeypatch.setattr(subgenres, "account_key", lambda request: CONTA)
    app = FastAPI()
    app.include_router(subgenres.router)
    return TestClient(app), estado


def test_routes_return_429_without_a_listing_and_progress_otherwise(rotas):
    client, estado = rotas
    assert client.get("/api/subgenres/enrich").json()["running"] is False
    assert client.post("/api/subgenres/enrich").json()["running"] is False
    assert client.delete("/api/subgenres/enrich").status_code == 200

    estado["429"] = True
    assert client.post("/api/subgenres/enrich").status_code == 429
    assert client.get("/api/subgenres/enrich").status_code == 200  # só consulta o que o job sabe


async def test_deezer_incomplete_is_not_cached_so_next_call_retries():
    detalhe_ok = {"valor": False}

    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"data": [{"id": 42, "title": "Um", "artist": {"name": "A"}, "link": "http://dz/42"}]})
        if not detalhe_ok["valor"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": 42, "bpm": 140, "link": "http://dz/42"})

    client = _cliente_deezer(handler)
    primeira = await deezer_client.get_track_info(client, "A", "Um")
    assert isinstance(primeira, deezer_client.Incomplete)

    detalhe_ok["valor"] = True
    segunda = await deezer_client.get_track_info(client, "A", "Um")
    assert not isinstance(segunda, deezer_client.Incomplete)
    assert segunda["bpm"] == 140.0


async def test_job_retries_deezer_detail_failure_in_the_same_process(monkeypatch):
    # Sem trocar get_many: a falha do detalhe passa pelo cliente real (e seus caches).
    estado = {"detalhe": False}

    def handler(req):
        if req.url.path.endswith("/search"):
            return httpx.Response(200, json={"data": [{"id": 42, "title": "Faixa a", "artist": {"name": "Artista"}, "link": "u"}]})
        if not estado["detalhe"]:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": 42, "bpm": 150, "link": "u"})

    async def tags(*a, **k):
        return [Tag("psytrance", 100.0)]

    real = httpx.AsyncClient
    monkeypatch.setattr(enrichment_job.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(lastfm_client, "get_artist_tags", tags)
    monkeypatch.setattr(lastfm_client, "get_track_tags", tags)

    digests = _digests(_t("a"))
    await _rodar(digests)
    assert evidence_store.get_many(["a"])["a"].deezer_checked_at is None

    estado["detalhe"] = True
    await _rodar(digests)
    ev = evidence_store.get_many(["a"])["a"]
    assert (ev.bpm, ev.deezer_id) == (150.0, 42) and ev.deezer_checked_at is not None


# ── correções da revisão final ───────────────────────────────────────────────


async def test_deezer_fallback_failure_after_empty_strict_is_not_not_found():
    # A busca estrita responde vazia; a livre falha: não dá para dizer "não tem".
    def handler(req):
        if req.url.params.get("q", "").startswith("artist:"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(503)

    info = await deezer_client.get_track_info(_cliente_deezer(handler), "Fallback", "Caiu")
    assert not isinstance(info, NotFound)
    assert info["deezer_id"] is None
    assert deezer_client.enrichment_store.get_deezer_match("fallback::caiu") is None


async def test_deezer_strict_failure_then_empty_fallback_is_not_not_found():
    def handler(req):
        if req.url.params.get("q", "").startswith("artist:"):
            return httpx.Response(503)
        return httpx.Response(200, json={"data": []})

    info = await deezer_client.get_track_info(_cliente_deezer(handler), "Estrita", "Caiu")
    assert not isinstance(info, NotFound)
    assert deezer_client.enrichment_store.get_deezer_match("estrita::caiu") is None


def test_pending_skips_tracks_without_artist_or_name():
    digests = _digests(_t("a"), _t("b", artists=()), {"id": "c", "name": "", "artists": ["X"], "genres": []})
    assert [t["id"] for t in enrichment_job.pending_tracks(digests)] == ["a"]


async def test_errors_are_capped_with_a_total_count(fontes):
    n = enrichment_job.MAX_ERRORS + 5
    tracks = [_t(f"f{i}") for i in range(n)]
    fontes.falha_faixa = {t["name"] for t in tracks}
    await _rodar(_digests(*tracks))

    progress = enrichment_job.progress_dict(CONTA)
    assert progress["error_count"] == n
    assert len(progress["errors"]) == enrichment_job.MAX_ERRORS
    # Ficam as mais recentes: a última faixa está lá, a primeira não.
    assert any(e.startswith(f"Faixa f{n - 1}:") for e in progress["errors"])
    assert not any(e.startswith("Faixa f0:") for e in progress["errors"])
